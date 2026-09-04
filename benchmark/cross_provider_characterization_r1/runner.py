"""Freeze, run, and report the bounded cross-provider R1 comparison.

The task source/evaluator is imported from the frozen R1.1 implementation;
this runner adds only cross-provider identity, validation, execution, and
derived-report semantics. Gemini Low evidence is copied as a historical
anchor, never re-executed.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import signal
import statistics
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark.adapters import DeepSeekAdapter, MiniMaxAdapter
from benchmark.edit_scope import matches_edit_scope
from benchmark.provenance import validate_git_identity
from benchmark.v2.telemetry import parse_trace
from delegation.config import load_config
from ekalavya.catalogue import load_catalogue
from ekalavya.config import config_root
from ekalavya.harness_registry import current_registry, validate_registry
from ekalavya.ledger import (
    connect, default_state_dir, finalize_run, record_benchmark_suite,
    record_benchmark_task, record_cost, record_harness, record_request_metric,
    record_run, record_task_attempt,
)
from ekalavya.schema import CandidateIdentity

from . import (
    CONFIGS, EVALUATION_CLASS, FAMILIES, R1_1_SHA, R1_1_SUITE, RETRIES,
    RUN_ORDER, SEEDS, SUITE_NAME, SUITE_SOURCE_PATHS, SUITE_VERSION,
    TIMEOUT_SECONDS,
)
from benchmark.gemini_reasoning_r1_1.evaluate import evaluate, visible_check_vector
from benchmark.gemini_reasoning_r1_1.generate import (
    TaskInstance, make_instance, materialize, task_hashes, workspace_digest,
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def state_root() -> Path:
    root = default_state_dir() / "experiments" / SUITE_NAME
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    return root


def _command(argv: list[str], *, timeout: int = 15) -> tuple[int, str, str]:
    try:
        result = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, "", str(exc)
    return result.returncode, result.stdout, result.stderr


def _r11_root() -> Path:
    return default_state_dir() / "experiments" / R1_1_SUITE


def instances() -> list[TaskInstance]:
    return [make_instance(family, SEEDS[family]) for family in FAMILIES]


def _identity(config: dict[str, str], version: str) -> dict[str, Any]:
    identity = CandidateIdentity(
        config["provider"], config["name"], config["model"], config["name"],
        capabilities={"reasoning_values": [config["reasoning"]]},
        serving_engine=config["transport"], serving_engine_version=version,
    )
    return {
        **identity.as_dict(), "identity_key": identity.identity_key,
        "reasoning": config["reasoning"], "harness": config["executable"],
        "harness_version": version, "transport": config["transport"],
        "billing": config["billing"],
    }


def discover() -> dict[str, Any]:
    """Inspect exact configured routes and launcher versions without inference."""
    catalogue = load_catalogue(config_root() / "catalogue.json")
    config_state = load_config()
    records = []
    for item in CONFIGS:
        matching = [entry for entry in catalogue if entry.get("provider_model_id") == item["model"] and entry.get("provider") == item["provider"]]
        if len(matching) != 1:
            raise RuntimeError(f"exact catalogue identity unavailable for {item['model']!r}")
        provider_entry = config_state.get("providers", {}).get(item["provider"], {})
        model_entry = config_state.get("models", {}).get(item["name"], {})
        if not provider_entry.get("enabled", True) or not model_entry.get("enabled", True):
            raise RuntimeError(f"candidate unavailable in user configuration: {item['name']}")
        code, stdout, stderr = _command([item["executable"], "--version"])
        version = (stdout or stderr).strip() or "unknown"
        if code != 0:
            raise RuntimeError(f"{item['executable']} version inspection failed: {version}")
        entry = matching[0]
        records.append({
            "profile": item["name"], "provider": item["provider"],
            "family": entry.get("family"), "provider_model_id": item["model"],
            "reasoning": item["reasoning"], "transport": item["transport"],
            "harness": item["executable"], "harness_version": version,
            "identity_key": entry.get("identity_key"),
            "catalogue_lifecycle": entry.get("lifecycle"),
            "availability": {"provider_enabled": provider_entry.get("enabled", True), "model_enabled": model_entry.get("enabled", True), "effective_enabled": True},
            "billing_class": item["billing"], "discovery_timestamp": now(),
        })
    result = {
        "timestamp": now(), "client": "Ekalavya configured provider-profile launchers",
        "client_version": "0.3.0", "candidates": records,
        "anchor": {"suite": R1_1_SUITE, "suite_git_sha": R1_1_SHA, "model": "gemini-3.8-flash-low", "harness": "agy", "harness_version": "1.1.26", "collection": "earlier retained evidence; not re-executed"},
        "request_metric_semantics": "harness_session", "tool_event_telemetry": "unavailable", "token_metric_semantics": "harness_reported_usage",
        "cost_semantics": {"actual": "provider_reported_cost", "calculated": "calculated_cost", "api_equivalent": "api_equivalent_cost", "unavailable": "null/unknown when not exposed"},
    }
    (state_root() / "discovery.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def _write_design_artifacts(items: list[TaskInstance]) -> None:
    root = state_root()
    for instance in items:
        spec = root / "task-specifications" / f"{instance.family}.md"
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text(f"# {instance.family}\n\n{instance.prompt}\n\nCandidate-visible README:\n\n{instance.files['README.md']}\n", encoding="utf-8")
        verifier = root / "verifier-contracts" / f"{instance.family}.py"
        verifier.parent.mkdir(parents=True, exist_ok=True)
        verifier.write_text(instance.files["tests/test_contract.py"], encoding="utf-8")
        scope = root / "edit-scopes" / f"{instance.family}.json"
        scope.parent.mkdir(parents=True, exist_ok=True)
        scope.write_text(json.dumps({"family": instance.family, "editable": list(instance.editable), "immutable": list(instance.immutable), "generated_noise_excluded": ["__pycache__/**", ".pytest_cache/**", "*.pyc"]}, indent=2, sort_keys=True) + "\n")
        snapshot = root / "baseline-task-snapshots" / instance.family
        snapshot.mkdir(parents=True, exist_ok=True)
        for name, content in instance.files.items():
            if name.startswith("tests/"):
                continue
            destination = snapshot / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")


def _copy_anchor() -> list[dict[str, Any]]:
    source_root = _r11_root()
    source_evidence = source_root / "evidence"
    destination = state_root() / "provenance" / "gemini-r1.1-anchor"
    destination.mkdir(parents=True, exist_ok=True)
    result = []
    for family in FAMILIES:
        source = source_evidence / f"low-{family}-202610{4 + FAMILIES.index(family):02d}.json"
        if not source.is_file():
            raise RuntimeError(f"missing retained Gemini anchor evidence: {source.name}")
        item = json.loads(source.read_text())
        if item.get("status") != "completed" or item.get("final_score") != 100.0 or item.get("final_check_vector") != [True] * 8:
            raise RuntimeError(f"Gemini anchor is not a clean full solve: {source.name}")
        safe = {key: item.get(key) for key in ("experiment", "evaluation_class", "run_id", "requested", "resolved", "started_at", "ended_at", "wall_seconds", "status", "timed_out", "harness_failure", "changed_files", "prohibited_changed_files", "evaluator_tampering", "request_count", "request_metric_semantics", "tool_event_telemetry", "token_metric_semantics", "final_check_vector", "baseline_score", "baseline_check_vector", "final_score", "delta_score", "normalized_improvement", "full_pass", "task")}
        safe["source_evidence"] = str(source.relative_to(source_root))
        (destination / source.name).write_text(json.dumps(safe, indent=2, sort_keys=True) + "\n")
        result.append(safe)
    return result


def _frozen_task_validation(items: list[TaskInstance]) -> dict[str, Any]:
    old_root = _r11_root()
    old_preflight = old_root / "validation" / "preflight.json"
    old_reference = old_root / "validation" / "reference-validation.json"
    if not old_preflight.is_file() or not old_reference.is_file():
        raise RuntimeError("retained R1.1 validation metadata is missing")
    old = json.loads(old_preflight.read_text())
    reference = json.loads(old_reference.read_text())
    if old.get("provenance", {}).get("git_sha") != R1_1_SHA or reference.get("passed") is not True:
        raise RuntimeError("R1.1 provenance/reference identity is not authoritative")
    ref_by_family = {item["family"]: item for item in reference.get("tasks", [])}
    anchor_by_family = {}
    for path in (old_root / "evidence").glob("low-*.json"):
        item = json.loads(path.read_text())
        if item.get("task", {}).get("family") in FAMILIES:
            anchor_by_family[item["task"]["family"]] = item
    results = []
    for instance in items:
        values = task_hashes(instance)
        anchor = anchor_by_family.get(instance.family, {})
        task = anchor.get("task", {})
        baseline = next((item for item in old.get("baseline", {}).get("tasks", []) if item.get("family") == instance.family), None)
        ref = ref_by_family.get(instance.family)
        hashes_match = all(task.get(key) == values[key] for key in values)
        baseline_match = bool(baseline and baseline.get("baseline_score") in {37.5, 50.0, 25.0} and baseline.get("baseline_check_vector") == next(item["baseline_check_vector"] for item in old["baseline"]["tasks"] if item["family"] == instance.family))
        expected = {"R1_maintenance": (37.5, [True, False, True, False, True, False, False, False]), "R2_api_compat": (50.0, [True, False, False, False, True, False, True, True]), "R3_scientific_pipeline": (50.0, [True, False, True, False, False, True, False, True]), "R4_config_state": (25.0, [False, False, False, True, False, True, False, False])}[instance.family]
        baseline_exact = bool(baseline and baseline.get("baseline_score") == expected[0] and baseline.get("baseline_check_vector") == expected[1] and baseline.get("visible_controller_parity") is True)
        reference_exact = bool(ref and ref.get("reference_validation_passed") is True and ref.get("reference_score") == 100.0 and ref.get("reference_check_vector") == [True] * 8 and ref.get("visible_reference_vector") == [True] * 8)
        results.append({"family": instance.family, "seed": instance.seed, "hashes": values, "hashes_match_r1_1": hashes_match, "baseline_exact": baseline_exact, "reference_exact": reference_exact, "reference_validation_identity": {"suite": R1_1_SUITE, "suite_git_sha": R1_1_SHA, "source_sha256": sha(old_reference.read_bytes())}})
    return {"status": "pass" if all(item["hashes_match_r1_1"] and item["baseline_exact"] and item["reference_exact"] for item in results) else "fail", "r1_1_suite": R1_1_SUITE, "r1_1_sha": R1_1_SHA, "tasks": results}


def _scope_validation(items: list[TaskInstance]) -> dict[str, Any]:
    results = []
    for instance in items:
        source = next(name for name in instance.files if name.endswith(".py") and not name.startswith("tests/"))
        nested = f"{source.split('/', 1)[0]}/nested/{source.rsplit('/', 1)[-1]}"
        immutable = next(name for name in instance.files if name.startswith("tests/"))
        checks = {
            "allowed_direct_source": matches_edit_scope(source, instance.editable),
            "allowed_nested_source": matches_edit_scope(nested, instance.editable),
            "immutable_tests_denied": not matches_edit_scope(immutable, instance.editable),
            "unrelated_denied": not matches_edit_scope("unrelated/escape.py", instance.editable),
            "traversal_denied": not matches_edit_scope("../escape.py", instance.editable),
            "absolute_denied": not matches_edit_scope("/tmp/escape.py", instance.editable),
            "generated_noise_ignored": True,
        }
        results.append({"family": instance.family, "checks": checks, "status": "pass" if all(checks.values()) else "fail"})
    return {"status": "pass" if all(item["status"] == "pass" for item in results) else "fail", "tasks": results}


def freeze() -> dict[str, Any]:
    root = state_root(); items = instances()
    discovery = discover()
    provenance = validate_git_identity(Path(__file__).resolve().parents[2], SUITE_SOURCE_PATHS)
    registry = current_registry(); validate_registry(registry)
    frozen = _frozen_task_validation(items)
    scopes = _scope_validation(items)
    if frozen["status"] != "pass" or scopes["status"] != "pass":
        raise RuntimeError("exact frozen-task or edit-scope validation failed")
    anchors = _copy_anchor()
    validation = {
        "status": "pass", "inference_authorized": True, "portfolio_frozen": True,
        "frozen_task_validation": frozen, "edit_scope_validation": scopes,
        "gold_accessibility_gate": {"status": "pass", "answer_bearing_repair_source": False, "method": "reuse of authoritative R1.1 pass metadata; no reference source retained"},
        "candidate_contamination": {"deepseek": "fresh external candidate; excluded from R1.1 authorship/review", "minimax": "fresh external candidate; excluded from R1.1 authorship/review"},
        "provenance": provenance, "anchor": {"suite": R1_1_SUITE, "git_sha": R1_1_SHA, "records": len(anchors)},
        "run_order": [[CONFIGS[c]["name"], FAMILIES[t]] for c, t in RUN_ORDER], "timeout_seconds": TIMEOUT_SECONDS, "retries": RETRIES, "created_at": now(),
    }
    (root / "validation").mkdir(exist_ok=True)
    (root / "validation" / "preflight.json").write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n")
    (root / "validation" / "frozen-task-validation.json").write_text(json.dumps(frozen, indent=2, sort_keys=True) + "\n")
    (root / "validation" / "edit-scope-validation.json").write_text(json.dumps(scopes, indent=2, sort_keys=True) + "\n")
    _write_design_artifacts(items)
    (root / "configuration-summary.json").write_text(json.dumps({"suite": SUITE_NAME, "version": SUITE_VERSION, "evaluation_class": EVALUATION_CLASS, "task_source_suite": R1_1_SUITE, "task_source_sha": R1_1_SHA, "configs": CONFIGS, "seeds": SEEDS, "attempt_timeout_seconds": TIMEOUT_SECONDS, "retries": RETRIES, "run_order": validation["run_order"], "anchor_reused": True}, indent=2, sort_keys=True) + "\n")
    return {"suite_git_sha": provenance["git_sha"], "task_source_sha": R1_1_SHA, "frozen_task_validation": frozen["status"], "edit_scope_validation": scopes["status"], "timeout_seconds": TIMEOUT_SECONDS, "run_order": validation["run_order"]}


def _snapshot(workspace: Path) -> dict[str, str]:
    result = {}
    for path in workspace.rglob("*"):
        if not path.is_file() or any(part in {"__pycache__", ".pytest_cache"} for part in path.parts) or path.suffix == ".pyc":
            continue
        result[path.relative_to(workspace).as_posix()] = sha(path.read_bytes())
    return result


def _terminate(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM); process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try: os.killpg(process.pid, signal.SIGKILL)
        except OSError: pass


def _adapter(config: dict[str, str]) -> Any:
    if config["name"] == "deepseek-flash":
        return DeepSeekAdapter(name="deepseek-flash", model=config["model"])
    return MiniMaxAdapter(model=config["model"])


def run_attempt(conn: Any, suite_id: int, task_db_id: int, instance: TaskInstance, config: dict[str, str], root: Path, harness_id: int, version: str) -> dict[str, Any]:
    key = f"{config['name']}-{instance.family}-{instance.seed}"
    workspace = root / "workspaces" / key
    materialize(instance, workspace); before = _snapshot(workspace)
    resolved = _identity(config, version)
    requested = {"experiment": SUITE_NAME, "profile": config["name"], "provider": config["provider"], "family": config["name"], "provider_model_id": config["model"], "model": config["model"], "reasoning": config["reasoning"], "harness": config["executable"], "transport": config["transport"], "evaluation_class": EVALUATION_CLASS, "attempt_timeout_seconds": TIMEOUT_SECONDS}
    run_id = f"{SUITE_NAME}:{uuid.uuid4().hex}"; started = now(); output_dir = root / "evidence" / "raw" / key; output_dir.mkdir(parents=True, exist_ok=True)
    record_run(conn, run_id, requested, resolved=resolved, status="running", evaluation_class=EVALUATION_CLASS, provider=config["provider"], identity_key=resolved["identity_key"], harness_id=harness_id, billing_mode="metered_api", started_at=started)
    process = None; stdout = stderr = ""; code = -1; timed_out = False; harness_failure = False
    start = time.monotonic()
    try:
        process = subprocess.Popen(_adapter(config).command(workspace, instance.prompt, output_dir), cwd=workspace, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, "BENCHMARK_WORKSPACE": str(workspace)}, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=TIMEOUT_SECONDS); code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True; _terminate(process); stdout, stderr = process.communicate(); code = -1
    except OSError as exc:
        stderr = str(exc); harness_failure = True
    wall = time.monotonic() - start; after = _snapshot(workspace)
    changed = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
    scope = next(item for item in json.loads((root / "validation" / "frozen-task-validation.json").read_text())["tasks"] if item["family"] == instance.family)
    editable = instance.editable
    prohibited = sorted(name for name in changed if not matches_edit_scope(name, editable))
    tampering = bool(prohibited)
    requests = parse_trace(stdout)
    telemetry_models = sorted({item.model for item in requests if item.model})
    identity_mismatch = bool(telemetry_models and config["model"] not in telemetry_models)
    assessment = evaluate(instance, workspace) if not timed_out else {"check_vector": [], "score": None, "full_pass": False}
    vector = assessment.get("check_vector", [])
    malformed = not timed_out and len(vector) != 8
    if timed_out: status = "explicit_timeout"
    elif harness_failure or code != 0: status = "harness_failure"
    elif identity_mismatch: status = "invalid_identity"
    elif malformed: status = "malformed_evaluator"
    elif tampering: status = "evaluator_tampering"
    else: status = "completed"
    baseline = next(item for item in json.loads((root / "validation" / "frozen-task-validation.json").read_text())["tasks"] if item["family"] == instance.family)
    expected_baselines = {"R1_maintenance": (37.5, [True, False, True, False, True, False, False, False]), "R2_api_compat": (50.0, [True, False, False, False, True, False, True, True]), "R3_scientific_pipeline": (50.0, [True, False, True, False, False, True, False, True]), "R4_config_state": (25.0, [False, False, False, True, False, True, False, False])}
    baseline_score, baseline_vector = expected_baselines[instance.family]
    scored = status == "completed"; score = assessment.get("score") if scored else None; final_vector = vector if scored else None
    delta = score - baseline_score if score is not None else None; normalized = delta / (100.0 - baseline_score) if delta is not None else None
    evidence = {"experiment": SUITE_NAME, "evaluation_class": EVALUATION_CLASS, "run_id": run_id, "requested": requested, "resolved": resolved, "started_at": started, "ended_at": now(), "wall_seconds": wall, "exit_code": code, "status": status, "timed_out": timed_out, "harness_failure": harness_failure, "changed_files": changed, "prohibited_changed_files": prohibited, "evaluator_tampering": tampering, "identity_match": not identity_mismatch, "request_count": len(requests) or None, "request_metric_semantics": "harness_session", "tool_events": None, "tool_event_telemetry": "unavailable", "token_metric_semantics": "harness_reported_usage", "telemetry_model_ids": telemetry_models or None, "final_check_vector": final_vector, "baseline_score": baseline_score, "baseline_check_vector": baseline_vector, "final_score": score, "delta_score": delta, "normalized_improvement": normalized, "full_pass": bool(assessment.get("full_pass")) if scored else None, "cost": {"provider_reported_cost": None, "calculated_cost": None, "api_equivalent_cost": None, "currency": None, "cost_source": "unavailable: provider/harness did not expose authoritative cost"}, "assessment": assessment, "task": {"suite": SUITE_NAME, "version": SUITE_VERSION, "source_suite": R1_1_SUITE, "source_suite_sha": R1_1_SHA, "family": instance.family, "task_id": instance.task_id, "seed": instance.seed, "workspace_hash": workspace_digest(workspace), **task_hashes(instance), "suite_git_sha": json.loads((root / "validation" / "preflight.json").read_text())["provenance"]["git_sha"]}, "stdout_sha256": sha(stdout.encode()), "stderr_sha256": sha(stderr.encode())}
    evidence_path = root / "evidence" / f"{key}.json"; evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    record_task_attempt(conn, run_id, task_db_id, score=score, public_score=score, invariant_score=score, scope_compliant=not tampering, wall_seconds=wall, baseline_score=baseline_score, baseline_check_vector=baseline_vector, final_check_vector=final_vector, delta_score=delta, normalized_improvement=normalized, evaluator_tampering=tampering, prohibited_changed_files=prohibited, metadata=evidence)
    for metric in requests:
        record_request_metric(conn, run_id, metric.json())
    fields = {field: [getattr(item, field) for item in requests if getattr(item, field) is not None] for field in ("input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens")}
    record_cost(conn, run_id, billing_mode="metered_api", cost_source="unavailable: provider/harness did not expose authoritative cost", input_tokens=sum(fields["input_tokens"]) if fields["input_tokens"] else None, output_tokens=sum(fields["output_tokens"]) if fields["output_tokens"] else None, cached_input_tokens=sum(fields["cache_read_tokens"]) if fields["cache_read_tokens"] else None, reasoning_tokens=sum(fields["reasoning_tokens"]) if fields["reasoning_tokens"] else None)
    finalize_run(conn, run_id, ended_at=evidence["ended_at"], status=status, raw_evidence_path=str(evidence_path), raw_evidence_sha256=sha(evidence_path.read_bytes()))
    return evidence


def run_sweep() -> dict[str, Any]:
    root = state_root(); preflight = json.loads((root / "validation" / "preflight.json").read_text())
    if not preflight.get("portfolio_frozen") or not preflight.get("inference_authorized"):
        raise RuntimeError("cross-provider inference gate is not authorized")
    provenance = validate_git_identity(Path(__file__).resolve().parents[2], SUITE_SOURCE_PATHS)
    if provenance["git_sha"] != preflight["provenance"]["git_sha"]:
        raise RuntimeError("provenance changed after freeze")
    discovery_data = discover(); items = instances()
    conn = connect(); harness_ids = {}
    for config, record in zip(CONFIGS, discovery_data["candidates"]):
        harness_ids[config["name"]] = record_harness(conn, config["executable"], version=record["harness_version"], adapter_version="benchmark.adapters." + ("DeepSeekAdapter" if config["provider"] == "deepseek" else "MiniMaxAdapter"), transport="codex", capabilities={"exact_model_selection": "supported", "reasoning_selection": "supported", "writable_workspace": "supported", "filesystem_containment": "unsupported", "tool_network_containment": "unsupported", "provider_transport_available": "supported", "telemetry": "supported", "tool_trace": "unavailable", "token_usage": "supported", "cost_usage": "unavailable"}, telemetry={"request_metric_semantics": "harness_session", "tool_event_telemetry": "unavailable", "token_metric_semantics": "harness_reported_usage"}, eligibility={"ordinary": "supported", "public_characterization": "supported", "hidden_benchmark": "unsupported"}, evidence_label=SUITE_NAME, observed_at=record["discovery_timestamp"])
    suite_id = record_benchmark_suite(conn, SUITE_NAME, "cross_provider", SUITE_VERSION, git_sha=provenance["git_sha"], evaluation_class=EVALUATION_CLASS, metadata={"task_source_suite": R1_1_SUITE, "task_source_sha": R1_1_SHA, "configs": CONFIGS, "timeout_seconds": TIMEOUT_SECONDS, "retries": RETRIES})
    baseline_values = {"R1_maintenance": (37.5, [True, False, True, False, True, False, False, False]), "R2_api_compat": (50.0, [True, False, False, False, True, False, True, True]), "R3_scientific_pipeline": (50.0, [True, False, True, False, False, True, False, True]), "R4_config_state": (25.0, [False, False, False, True, False, True, False, False])}
    task_db = {}
    for instance in items:
        values = task_hashes(instance); score, vector = baseline_values[instance.family]
        task_db[instance.family] = record_benchmark_task(conn, suite_id, family=instance.family, task_id=instance.task_id, variant_seed=str(instance.seed), content_hash=values["generated_workspace_hash"], prompt_hash=values["task_spec_hash"], evaluator_hash=values["visible_verifier_hash"], baseline_score=score, baseline_check_vector=vector, task_spec_hash=values["task_spec_hash"], allowed_edit_manifest_hash=values["allowed_edit_manifest_hash"], reference_validation_passed=True)
    attempts = []
    for config_index, task_index in RUN_ORDER:
        attempts.append(run_attempt(conn, suite_id, task_db[FAMILIES[task_index]], items[task_index], CONFIGS[config_index], root, harness_ids[CONFIGS[config_index]["name"]], discovery_data["candidates"][config_index]["harness_version"]))
    result = {"experiment": SUITE_NAME, "suite": SUITE_NAME, "version": SUITE_VERSION, "evaluation_class": EVALUATION_CLASS, "suite_git_sha": provenance["git_sha"], "report_generation_code_identity": provenance["git_sha"], "task_source_suite": R1_1_SUITE, "task_source_sha": R1_1_SHA, "attempt_timeout_seconds": TIMEOUT_SECONDS, "retries": RETRIES, "attempts": len(attempts), "completed": sum(item["status"] == "completed" for item in attempts), "timeouts": sum(item["status"] == "explicit_timeout" for item in attempts), "harness_failures": sum(item["status"] == "harness_failure" for item in attempts), "evaluator_tampering": sum(item["status"] == "evaluator_tampering" for item in attempts), "invalid_identity": sum(item["status"] == "invalid_identity" for item in attempts), "malformed_evaluator": sum(item["status"] == "malformed_evaluator" for item in attempts), "discovery": discovery_data}
    (root / "run-summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def _new_evidence() -> list[dict[str, Any]]:
    return [json.loads(path.read_text()) for path in sorted((state_root() / "evidence").glob("*.json"))]


def _usage(item: dict[str, Any]) -> dict[str, int | None]:
    root = state_root(); conn = connect(); run_id = item["run_id"]
    row = conn.execute("SELECT input_tokens,output_tokens,cache_read_tokens,reasoning_tokens FROM request_metrics WHERE run_id=? ORDER BY id LIMIT 1", (run_id,)).fetchone()
    return {field: (row[index] if row else None) for index, field in enumerate(("input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens"))}


def report() -> Path:
    root = state_root(); new = _new_evidence(); anchor = []
    for path in sorted((root / "provenance" / "gemini-r1.1-anchor").glob("*.json")):
        item = json.loads(path.read_text()); item["source"] = "historical_gemini_anchor"; anchor.append(item)
    rows = []
    for item in anchor + new:
        usage = _usage(item) if item in new else {"input_tokens": None, "output_tokens": item.get("output_tokens"), "cache_read_tokens": item.get("cache_read_tokens"), "reasoning_tokens": item.get("reasoning_tokens")}
        resolved = item.get("resolved", {}); requested = item.get("requested", {})
        rows.append({"source": item.get("source", "new_candidate"), "configuration": resolved.get("provider_model_id", requested.get("provider_model_id")), "provider": resolved.get("provider", requested.get("provider")), "reasoning": resolved.get("reasoning", requested.get("reasoning")), "task": item["task"]["family"], "status": item.get("status"), "baseline_score": item.get("baseline_score"), "baseline_vector": "".join("P" if x else "F" for x in item.get("baseline_check_vector", [])), "final_score": item.get("final_score"), "final_vector": "".join("P" if x else "F" for x in item.get("final_check_vector") or []), "delta_score": item.get("delta_score"), "normalized_improvement": item.get("normalized_improvement"), "full_pass": item.get("full_pass"), "evaluator_tampering": item.get("evaluator_tampering"), "prohibited_changed_files": ";".join(item.get("prohibited_changed_files", [])), "wall_seconds": item.get("wall_seconds"), "request_count": item.get("request_count"), "request_metric_semantics": item.get("request_metric_semantics"), "tool_event_telemetry": item.get("tool_event_telemetry"), **usage})
    fields = list(rows[0]) if rows else ["configuration", "task", "status"]
    with (root / "task-check-matrix.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
    lines = ["# Cross-provider characterization R1 matrix", "", "Gemini rows are historical R1.1 Low anchors; DeepSeek and MiniMax rows are the eight new attempts.", "", "| Source | Configuration | Task | Status | Baseline | Final | Delta | Vector | Full | Tamper | Wall s | Input | Output | Cache | Reasoning |", "|---|---|---|---|---:|---:|---:|---|---|---|---:|---:|---:|---:|---:|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row[key] if row[key] is not None else "null") for key in ("source", "configuration", "task", "status", "baseline_score", "final_score", "delta_score", "final_vector", "full_pass", "evaluator_tampering", "wall_seconds", "input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens")) + " |")
    (root / "task-check-matrix.md").write_text("\n".join(lines) + "\n")
    candidates = [row for row in rows if row["source"] == "new_candidate"]
    summaries = []
    for config in CONFIGS:
        group = [row for row in candidates if row["configuration"] == config["model"]]
        clean = [row for row in group if row["status"] == "completed" and not row["evaluator_tampering"] and row["final_score"] is not None]
        summaries.append({"configuration": config["name"], "provider": config["provider"], "model": config["model"], "attempted": len(group), "completed_clean": len(clean), "completion_rate": len(clean) / len(group) if group else None, "quality_on_clean_completed": statistics.mean(r["final_score"] for r in clean) if clean else None, "median_final": statistics.median(r["final_score"] for r in clean) if clean else None, "full_solves": sum(r["full_pass"] is True for r in clean), "scope_violations": sum(r["evaluator_tampering"] is True for r in group), "mean_wall_attempted": statistics.mean(r["wall_seconds"] for r in group) if group else None, "mean_delta_clean": statistics.mean(r["delta_score"] for r in clean) if clean else None, "usage_totals": {field: sum(r[field] for r in group if r[field] is not None) if any(r[field] is not None for r in group) else None for field in ("input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens")}})
    (root / "configuration-summary.json").write_text(json.dumps({"suite": SUITE_NAME, "new_candidate_summaries": summaries, "gemini_anchor": {"source_suite": R1_1_SUITE, "source_sha": R1_1_SHA, "clean_full_solves": "4/4"}}, indent=2, sort_keys=True) + "\n")
    plots = {}
    import matplotlib.pyplot as plt
    for filename, key, title, ylabel in (("final-score.png", "final_score", "Final score by task/configuration", "score"), ("reliability.png", "completion_rate", "Clean completion rate", "rate"), ("wall-time.png", "wall_seconds", "Wall time by task/configuration", "seconds"), ("output-usage.png", "output_tokens", "AGY-reported output usage", "tokens")):
        observations = [r for r in rows if r["final_score"] is not None] if key == "final_score" else candidates
        if key == "completion_rate":
            observations = [{"configuration": s["configuration"], "task": "aggregate", key: s[key]} for s in summaries]
        observations = [r for r in observations if r.get(key) is not None]
        if not observations: plots[filename] = {"status": "skipped"}; continue
        labels = [f"{r['configuration']}\n{r['task']}" for r in observations]; values = [r[key] for r in observations]
        fig, ax = plt.subplots(figsize=(11, 5)); ax.bar(range(len(values)), values); ax.set_xticks(range(len(values)), labels, rotation=45, ha="right"); ax.set_title(title); ax.set_ylabel(ylabel); fig.tight_layout(); fig.savefig(root / filename); plt.close(fig); plots[filename] = {"status": "created", "observations": len(values)}
    (root / "plot-metadata.json").write_text(json.dumps(plots, indent=2, sort_keys=True) + "\n")
    (root / "telemetry-semantics.md").write_text("# Telemetry semantics\n\nRequest count is `harness_session` for both the historical AGY anchor and the Codex transport launchers. It is not a provider model request count. Tool-event telemetry is `unavailable`, not zero.\n")
    (root / "token-semantics.md").write_text("# Token semantics\n\nInput, output, cache-read, and reasoning fields are AGY/Codex-harness-reported usage. They are not verified provider billing tokens and are not assumed comparable across transports. Missing fields remain null.\n")
    cost_path = root / "provenance" / "cost-semantics.md"
    cost_path.parent.mkdir(parents=True, exist_ok=True)
    cost_path.write_text("# Cost semantics\n\nDeepSeek and MiniMax are configured PAYG routes. This study exposed no authoritative provider-charged, calculated, or API-equivalent cost, so all cost fields are null/unknown. Token counts are not used to infer cost.\n")
    run = json.loads((root / "run-summary.json").read_text())
    report_lines = ["# Cross-provider characterization R1", "", "Evaluation class: `public_characterization`. This is an operational configuration comparison, not a pure model-weight benchmark.", "", f"Frozen cross-provider suite SHA: `{run['suite_git_sha']}`.", f"Exact task source: `{R1_1_SUITE}` at `{R1_1_SHA}`. Fixed timeout: `{TIMEOUT_SECONDS}` seconds; retries: `0`.", "", "Gemini 3.8 Flash Low is a previously collected, clean R1.1 anchor and was not re-run. Stopped R1 evidence is not included.", "", "## Candidate summaries", "", "| Configuration | Clean quality | Full solves | Completion | Scope violations | Mean wall s | Usage totals |", "|---|---:|---:|---:|---:|---:|---|"]
    for s in summaries:
        report_lines.append(f"| {s['configuration']} | {s['quality_on_clean_completed']} | {s['full_solves']}/{s['completed_clean']} | {s['completed_clean']}/{s['attempted']} | {s['scope_violations']} | {s['mean_wall_attempted']} | `{json.dumps(s['usage_totals'], sort_keys=True)}` |")
    report_lines += ["", "## Interpretation", "", "The complete 8-attempt new matrix and the four historical Gemini anchor rows are in `task-check-matrix.md` and `.csv`. Correctness is conditional on clean scored completion; scope violations, timeouts, and harness failures remain separate. Provider and transport/harness effects are confounded by design and must not be attributed solely to model weights.", "", "## Exact run order", "", *[f"{i + 1}. {CONFIGS[c]['name']} × {FAMILIES[t]}" for i, (c, t) in enumerate(RUN_ORDER)], "", "## Semantics", "", "Request metrics are `harness_session`; tool telemetry is `unavailable`; usage is harness-reported and not verified billing. Cost is unavailable/null.", "", "Persistent defaults and provider availability were not changed."]
    (root / "REPORT.md").write_text("\n".join(report_lines) + "\n")
    (root / "AUDIT_REPORT.md").write_text(f"# Cross-provider R1 audit report\n\nThe R1.1 task portfolio was reproduced exactly from `{R1_1_SUITE}` at `{R1_1_SHA}` before inference. All four baseline vectors/scores, task hashes, reference validation identity, and real edit-scope checks matched. DeepSeek and MiniMax were excluded from R1.1 task design/review and were run only as candidates here. Gemini Low rows are historical anchors, not new calls.\n")
    return root / "REPORT.md"


def main(argv: list[str] | None = None) -> int:
    action = (argv or __import__("sys").argv[1:] or ["freeze"])[0]
    if action == "freeze": print(json.dumps(freeze(), indent=2, sort_keys=True)); return 0
    if action == "discover": print(json.dumps(discover(), indent=2, sort_keys=True)); return 0
    if action == "run": print(json.dumps(run_sweep(), indent=2, sort_keys=True)); return 0
    if action == "report": print(report()); return 0
    raise SystemExit(f"unknown command: {action}")


if __name__ == "__main__":
    raise SystemExit(main())
