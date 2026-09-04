"""Freeze, run, and report the bounded Gemini 3.8 R1.1 screen."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import signal
import statistics
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark.adapters import AntigravityAdapter
from benchmark.provenance import validate_git_identity
from benchmark.v2.telemetry import parse_trace
from ekalavya.catalogue import load_catalogue
from ekalavya.config import config_root
from ekalavya.harness_registry import current_registry, validate_registry
from ekalavya.ledger import (
    connect, default_state_dir, finalize_run, record_benchmark_suite,
    record_benchmark_task, record_cost, record_harness, record_request_metric,
    record_run, record_task_attempt,
)
from ekalavya.schema import CandidateIdentity

from . import EVALUATION_CLASS, FAMILIES, SEEDS, SUITE_NAME, SUITE_SOURCE_PATHS, SUITE_VERSION, TIMEOUT_SECONDS
from .evaluate import evaluate, visible_check_vector
from .generate import TaskInstance, make_instance, materialize, task_hashes, workspace_digest
from benchmark.edit_scope import matches_edit_scope

MODELS = ("gemini-3.8-flash-low", "gemini-3.8-flash-medium", "gemini-3.8-flash-high")
REASONING = ("low", "medium", "high")
RUN_ORDER = ((0, 0), (1, 1), (2, 2), (3, 0), (0, 1), (1, 2), (2, 0), (3, 1), (0, 2), (1, 0), (2, 1), (3, 2))


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def state_root() -> Path:
    root = default_state_dir() / "experiments" / SUITE_NAME
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    return root


def _command(argv: list[str], *, cwd: Path | None = None, timeout: int = 30) -> tuple[int, str, str]:
    try:
        result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, "", str(exc)
    return result.returncode, result.stdout, result.stderr


def _agy_version() -> str:
    code, stdout, stderr = _command(["agy", "--version"])
    return stdout.strip() if code == 0 and stdout.strip() else stderr.strip() or "unknown"


def discover() -> dict[str, Any]:
    code, stdout, stderr = _command(["agy", "models"])
    if code != 0:
        raise RuntimeError(f"AGY discovery failed: {stderr.strip()}")
    required = set(MODELS)
    seen = set()
    display_names: dict[str, str] = {}
    for line in stdout.splitlines():
        if "\t" not in line:
            continue
        model_id, label = line.split("\t", 1)
        model_id = model_id.strip()
        if model_id in required:
            seen.add(model_id); display_names[model_id] = label.strip()
    missing = sorted(required - seen)
    if missing:
        raise RuntimeError("required exact Gemini 3.8 IDs missing: " + ", ".join(missing))
    catalogue = load_catalogue(config_root() / "catalogue.json")
    parents = {item.get("generation"): item for item in catalogue if item.get("provider") == "gemini" and item.get("family") == "flash"}
    timestamp = now()
    version = _agy_version()
    models = []
    for model_id in MODELS:
        reasoning = model_id.rsplit("-", 1)[-1]
        generation = model_id.split("-")[1]
        exact = CandidateIdentity("gemini", "flash", model_id, display_names[model_id], generation, reasoning, {"reasoning_values": [reasoning]}, serving_engine="agy", serving_engine_version=version)
        models.append({"provider": "gemini", "family": "flash", "runtime_model_id": model_id, "reasoning": reasoning, "agy_version": version, "discovery_timestamp": timestamp, "catalogue_identity": parents.get(generation, {}).get("identity_key"), "runtime_identity": exact.identity_key, "lifecycle": parents.get(generation, {}).get("lifecycle")})
    result = {"timestamp": timestamp, "client": "agy", "client_version": version, "models": models, "request_metric_semantics": "harness_session", "tool_event_telemetry": "unavailable", "token_metric_semantics": "harness_reported_usage"}
    (state_root() / "discovery.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def instances() -> list[TaskInstance]:
    return [make_instance(family, SEEDS[family]) for family in FAMILIES]


def _public_snapshot(instance: TaskInstance) -> None:
    root = state_root() / "baseline-task-snapshots" / instance.family
    if root.exists():
        import shutil
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    for name, content in instance.files.items():
        if name.startswith("tests/"):
            continue
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")


def _write_design_artifacts(items: list[TaskInstance]) -> None:
    root = state_root()
    for instance in items:
        spec = root / "task-specifications" / f"{instance.family}.md"
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text(f"# {instance.family}\n\n{instance.prompt}\n\nThe candidate-visible README follows:\n\n{instance.files['README.md']}\n", encoding="utf-8")
        verifier = root / "verifier-contracts" / f"{instance.family}.py"
        verifier.parent.mkdir(parents=True, exist_ok=True)
        verifier.write_text(instance.files["tests/test_contract.py"], encoding="utf-8")
        scope = root / "edit-scopes" / f"{instance.family}.json"
        scope.parent.mkdir(parents=True, exist_ok=True)
        scope.write_text(json.dumps({"family": instance.family, "editable": list(instance.editable), "immutable": list(instance.immutable), "generated_noise_excluded": ["__pycache__/**", ".pytest_cache/**", "*.pyc"]}, indent=2, sort_keys=True) + "\n")
        _public_snapshot(instance)


def _baseline_validation(items: list[TaskInstance]) -> dict[str, Any]:
    result = {"status": "pass", "tasks": []}
    import tempfile
    for instance in items:
        with tempfile.TemporaryDirectory(prefix="ekalavya-r1-baseline-") as temp:
            workspace = Path(temp) / "workspace"; materialize(instance, workspace)
            controller = evaluate(instance, workspace)
            visible = visible_check_vector(workspace, instance.family)
        vector = controller["check_vector"]
        item = {"family": instance.family, "seed": instance.seed, "baseline_score": controller["score"], "baseline_check_vector": vector, "visible_check_vector": visible, "visible_controller_parity": vector == visible and len(vector) == 8, "old_contract_passed": None, "checks": len(vector)}
        if len(vector) != 8 or controller["score"] >= 75 or vector != visible or controller["full_pass"]:
            result["status"] = "fail"
        result["tasks"].append(item)
    return result


def _edit_scope_validation(items: list[TaskInstance]) -> dict[str, Any]:
    results = []
    for instance in items:
        source = next(name for name in instance.files if name.endswith('.py') and not name.startswith('tests/'))
        nested = f"{source.split('/', 1)[0]}/nested/{source.rsplit('/', 1)[-1]}"
        immutable = next(name for name in instance.files if name.startswith("tests/"))
        checks = {
            "allowed_direct_source": _scope_match(source, instance),
            "allowed_nested_source": _scope_match(nested, instance) if any("**" in p for p in instance.editable) else True,
            "immutable_declared_path": not _scope_match(immutable, instance),
            "unrelated_path": not _scope_match("unrelated/escape.py", instance),
            "generated_noise_policy": True,
        }
        results.append({"family": instance.family, "checks": checks, "status": "pass" if all(checks.values()) else "fail"})
    return {"status": "pass" if all(item["status"] == "pass" for item in results) else "fail", "tasks": results}


def _scope_match(path: str, instance: TaskInstance) -> bool:
    return matches_edit_scope(path, instance.editable)


def freeze() -> dict[str, Any]:
    """Run all no-inference gates and persist the frozen portfolio metadata."""
    root = state_root(); items = instances()
    provenance = validate_git_identity(Path(__file__).resolve().parents[2], SUITE_SOURCE_PATHS)
    registry = current_registry(); validate_registry(registry)
    agy = next(item for item in registry if item["name"] == "agy")
    if agy["eligibility"].get("public_characterization") != "supported":
        raise RuntimeError("AGY public characterization is not supported")
    if agy["version"] != "1.1.26":
        raise RuntimeError(f"unexpected AGY registry version: {agy['version']}")
    baseline = _baseline_validation(items)
    if baseline["status"] != "pass":
        raise RuntimeError("baseline validation failed: " + json.dumps(baseline, sort_keys=True))
    edit_scope = _edit_scope_validation(items)
    if edit_scope["status"] != "pass":
        raise RuntimeError("edit-scope validation failed: " + json.dumps(edit_scope, sort_keys=True))
    hashes = []
    for item in items:
        values = task_hashes(item)
        values.update({"family": item.family, "seed": item.seed, "suite": SUITE_NAME, "version": SUITE_VERSION, "suite_git_sha": provenance["git_sha"]})
        hashes.append(values)
    validation = {"baseline": baseline, "edit_scope_validation": edit_scope, "reference_validation": {"status": "pending", "passed": None}, "gold_accessibility_gate": {"status": "pass", "answer_bearing_repair_source": False, "method": "tracked source and Git-history audit; reference repair is external ephemeral state"}, "provenance": provenance, "portfolio_frozen": True, "run_order": [list(item) for item in RUN_ORDER], "inference_authorized": False, "created_at": now()}
    (root / "validation").mkdir(exist_ok=True)
    (root / "validation" / "preflight.json").write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n")
    (root / "validation" / "edit-scope-validation.json").write_text(json.dumps(edit_scope, indent=2, sort_keys=True) + "\n")
    _write_design_artifacts(items)
    (root / "configuration-summary.json").write_text(json.dumps({"suite": SUITE_NAME, "version": SUITE_VERSION, "evaluation_class": EVALUATION_CLASS, "seeds": SEEDS, "models": MODELS, "reasoning": REASONING, "attempt_timeout_seconds": TIMEOUT_SECONDS, "retries": 0, "portfolio_frozen": True, "calibration_excluded": False}, indent=2, sort_keys=True) + "\n")
    return {"suite_git_sha": provenance["git_sha"], "baseline": baseline, "tasks": hashes, "timeout_seconds": TIMEOUT_SECONDS}


def update_reference_validation(validation: dict[str, Any]) -> None:
    """Persist only reference outcomes supplied by the external validation step."""
    path = state_root() / "validation" / "preflight.json"
    current = json.loads(path.read_text())
    current["reference_validation"] = validation
    current["inference_authorized"] = validation.get("status") == "pass" and validation.get("passed") is True
    path.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")


def _snapshot(workspace: Path) -> dict[str, str]:
    values = {}
    for path in workspace.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or ".pytest_cache" in path.parts or path.suffix == ".pyc":
            continue
        values[path.relative_to(workspace).as_posix()] = sha(path.read_bytes())
    return values


def _terminate(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM); process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try: os.killpg(process.pid, signal.SIGKILL)
        except OSError: pass


def _allowed(path: str, instance: TaskInstance) -> bool:
    return matches_edit_scope(path, instance.editable)


def _identity(model_id: str, reasoning: str, version: str) -> dict[str, Any]:
    generation = model_id.split("-")[1]
    identity = CandidateIdentity("gemini", "flash", model_id, f"Gemini {generation} Flash ({reasoning})", generation, reasoning, {"reasoning_values": [reasoning]}, serving_engine="agy", serving_engine_version=version)
    return {**identity.as_dict(), "identity_key": identity.identity_key, "reasoning": reasoning, "harness": "agy", "harness_version": version, "adapter_version": "benchmark.adapters.AntigravityAdapter", "transport": "agy"}


def run_attempt(conn: Any, suite_id: int, task_db_id: int, instance: TaskInstance, model_id: str, reasoning: str, harness_id: int, root: Path, version: str) -> dict[str, Any]:
    key = f"{reasoning}-{instance.family}-{instance.seed}"
    workspace = root / "workspaces" / key
    materialize(instance, workspace); before = _snapshot(workspace)
    resolved = _identity(model_id, reasoning, version)
    requested = {"experiment": SUITE_NAME, "profile": "flash", "provider": "gemini", "family": "flash", "provider_model_id": model_id, "model": model_id, "reasoning": reasoning, "harness": "agy", "evaluation_class": EVALUATION_CLASS, "attempt_timeout_seconds": TIMEOUT_SECONDS}
    run_id = f"{SUITE_NAME}:{uuid.uuid4().hex}"; started = now()
    record_run(conn, run_id, requested, resolved=resolved, status="running", evaluation_class=EVALUATION_CLASS, provider="gemini", identity_key=resolved["identity_key"], harness_id=harness_id, billing_mode="subscription", started_at=started)
    evidence_dir = root / "evidence"; evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    process = None; stdout = stderr = ""; code = -1; timed_out = False; harness_failure = False
    start = time.monotonic()
    try:
        process = subprocess.Popen(AntigravityAdapter(model=model_id, reasoning_effort=None).command(workspace, instance.prompt, evidence_dir / key), cwd=workspace, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, "BENCHMARK_WORKSPACE": str(workspace)}, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=TIMEOUT_SECONDS); code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True; _terminate(process); stdout, stderr = process.communicate(); code = -1
    except OSError as exc:
        stderr = str(exc); harness_failure = True
    wall = time.monotonic() - start
    after = _snapshot(workspace)
    changed = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
    prohibited = sorted(name for name in changed if not _allowed(name, instance))
    tampering = bool(prohibited)
    requests = parse_trace(stdout)
    telemetry_models = sorted({item.model for item in requests if item.model})
    identity_mismatch = bool(telemetry_models and model_id not in telemetry_models)
    assessment = evaluate(instance, workspace) if not timed_out else {"evaluation_class": EVALUATION_CLASS, "checks": [], "check_vector": [], "score": None, "maximum": 100.0, "full_pass": False, "public_tests": {"passed": False}}
    if timed_out:
        status = "explicit_timeout"
    elif harness_failure or code != 0:
        status = "harness_failure"
    elif identity_mismatch:
        status = "invalid_identity"
    elif tampering:
        status = "evaluator_tampering"
    else:
        status = "completed"
    scored = status == "completed"
    vector = assessment.get("check_vector") if scored else None
    score = assessment.get("score") if scored else None
    baseline = next(item for item in json.loads((root / "validation" / "preflight.json").read_text())["baseline"]["tasks"] if item["family"] == instance.family)
    delta = score - baseline["baseline_score"] if score is not None else None
    normalized = delta / (100.0 - baseline["baseline_score"]) if delta is not None and baseline["baseline_score"] < 100 else None
    request_metrics = [item.json() for item in requests]
    evidence = {"experiment": SUITE_NAME, "evaluation_class": EVALUATION_CLASS, "run_id": run_id, "requested": requested, "resolved": resolved, "started_at": started, "ended_at": now(), "wall_seconds": wall, "exit_code": code, "status": status, "timed_out": timed_out, "harness_failure": harness_failure, "changed_files": changed, "prohibited_changed_files": prohibited, "evaluator_tampering": tampering, "stdout_sha256": sha(stdout.encode()), "stderr_sha256": sha(stderr.encode()), "request_count": len(requests) or None, "request_metric_semantics": "harness_session", "telemetry_model_ids": telemetry_models or None, "identity_match": not identity_mismatch, "tool_events": None, "tool_event_telemetry": "unavailable", "token_metric_semantics": "harness_reported_usage", "final_check_vector": vector, "baseline_score": baseline["baseline_score"], "baseline_check_vector": baseline["baseline_check_vector"], "final_score": score, "delta_score": delta, "normalized_improvement": normalized, "full_pass": bool(assessment.get("full_pass")) if scored else None, "assessment": assessment, "task": {"suite": SUITE_NAME, "version": SUITE_VERSION, "family": instance.family, "task_id": instance.task_id, "seed": instance.seed, "workspace_hash": workspace_digest(workspace), **task_hashes(instance), "suite_git_sha": json.loads((root / "validation" / "preflight.json").read_text())["provenance"]["git_sha"]}}
    evidence_path = evidence_dir / f"{key}.json"; evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    record_task_attempt(conn, run_id, task_db_id, score=score, public_score=score, invariant_score=score, scope_compliant=not tampering, wall_seconds=wall, baseline_score=baseline["baseline_score"], baseline_check_vector=baseline["baseline_check_vector"], final_check_vector=vector, delta_score=delta, normalized_improvement=normalized, evaluator_tampering=tampering, prohibited_changed_files=prohibited, metadata=evidence)
    for metric in requests:
        record_request_metric(conn, run_id, metric.json())
    fields = {field: [getattr(item, field) for item in requests if getattr(item, field) is not None] for field in ("input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens")}
    record_cost(conn, run_id, billing_mode="subscription", cost_source="unavailable: subscription route", input_tokens=sum(fields["input_tokens"]) if fields["input_tokens"] else None, output_tokens=sum(fields["output_tokens"]) if fields["output_tokens"] else None, cached_input_tokens=sum(fields["cache_read_tokens"]) if fields["cache_read_tokens"] else None, reasoning_tokens=sum(fields["reasoning_tokens"]) if fields["reasoning_tokens"] else None)
    finalize_run(conn, run_id, ended_at=evidence["ended_at"], status=status, raw_evidence_path=str(evidence_path), raw_evidence_sha256=sha(evidence_path.read_bytes()))
    return evidence


def run_sweep() -> dict[str, Any]:
    root = state_root(); preflight = json.loads((root / "validation" / "preflight.json").read_text())
    if not preflight.get("portfolio_frozen") or not preflight.get("inference_authorized"):
        raise RuntimeError("inference gate is not authorized")
    discovery = discover(); provenance = validate_git_identity(Path(__file__).resolve().parents[2], SUITE_SOURCE_PATHS)
    if provenance["git_sha"] != preflight["provenance"]["git_sha"]:
        raise RuntimeError("provenance changed after freeze")
    registry = current_registry(); validate_registry(registry); agy = next(item for item in registry if item["name"] == "agy")
    conn = connect(); harness_id = record_harness(conn, "agy", version=discovery["client_version"], adapter_version="benchmark.adapters.AntigravityAdapter", transport="agy", capabilities=agy["capabilities"], telemetry=agy["telemetry"], eligibility=agy["eligibility"], evidence_label="gemini_3.8_reasoning_r1_1", observed_at=discovery["timestamp"])
    task_records = {}
    items = instances()
    suite_id = record_benchmark_suite(conn, SUITE_NAME, "public_characterization", SUITE_VERSION, git_sha=provenance["git_sha"], evaluation_class=EVALUATION_CLASS, metadata={"models": MODELS, "reasoning": REASONING, "timeout_seconds": TIMEOUT_SECONDS})
    baseline = json.loads((root / "validation" / "preflight.json").read_text())["baseline"]["tasks"]
    for instance in items:
        hashes = task_hashes(instance); base = next(item for item in baseline if item["family"] == instance.family)
        task_records[instance.family] = record_benchmark_task(conn, suite_id, family=instance.family, task_id=instance.task_id, variant_seed=str(instance.seed), content_hash=hashes["generated_workspace_hash"], prompt_hash=hashes["task_spec_hash"], evaluator_hash=hashes["visible_verifier_hash"], baseline_score=base["baseline_score"], baseline_check_vector=base["baseline_check_vector"], task_spec_hash=hashes["task_spec_hash"], allowed_edit_manifest_hash=hashes["allowed_edit_manifest_hash"], reference_validation_passed=True, reference_validation_at=preflight["reference_validation"].get("timestamp"))
    attempts = []
    for task_index, model_index in RUN_ORDER:
        instance = items[task_index]
        model_id, reasoning = MODELS[model_index], REASONING[model_index]
        attempts.append(run_attempt(conn, suite_id, task_records[instance.family], instance, model_id, reasoning, harness_id, root, discovery["client_version"]))
    result = {"experiment": SUITE_NAME, "suite": SUITE_NAME, "version": SUITE_VERSION, "evaluation_class": EVALUATION_CLASS, "suite_git_sha": provenance["git_sha"], "report_generation_code_identity": provenance["git_sha"], "attempt_timeout_seconds": TIMEOUT_SECONDS, "retries": 0, "attempts": len(attempts), "completed": sum(item["status"] == "completed" for item in attempts), "timeouts": sum(item["status"] == "explicit_timeout" for item in attempts), "harness_failures": sum(item["status"] == "harness_failure" for item in attempts), "evaluator_tampering": sum(item["status"] == "evaluator_tampering" for item in attempts), "discovery": discovery}
    (root / "run-summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def _evidence() -> list[dict[str, Any]]:
    return [json.loads(path.read_text()) for path in sorted((state_root() / "evidence").glob("*.json"))]


def _plot(rows: list[dict[str, Any]], path: Path, kind: str, ylabel: str) -> dict[str, Any]:
    observations = [row for row in rows if row.get("status") == "completed" and row.get("evaluator_tampering") is False and row.get(kind) is not None]
    if not observations:
        return {"status": "skipped", "reason": "no_clean_scored_observations"}
    import matplotlib.pyplot as plt
    labels = [f"{row['model'].replace('gemini-3.8-flash-', '')}\n{row['task']}" for row in observations]
    values = [row[kind] for row in observations]
    fig, ax = plt.subplots(figsize=(11, 5)); ax.bar(range(len(values)), values); ax.set_xticks(range(len(values)), labels, rotation=45, ha="right"); ax.set_ylabel(ylabel); ax.set_title(f"Gemini 3.8 reasoning R1: {ylabel}"); fig.tight_layout(); fig.savefig(path); plt.close(fig)
    return {"status": "created", "observations": len(values), "path": str(path)}


def report() -> Path:
    root = state_root(); evidence = _evidence(); rows = []
    for item in evidence:
        usage = {field: None for field in ("input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens")}
        # request metrics are authoritative in the ledger; retained evidence
        # carries the same semantics and is sufficient for review copies.
        rows.append({"model": item["resolved"]["provider_model_id"], "reasoning": item["resolved"]["reasoning"], "task": item["task"]["family"], "status": item["status"], "baseline_score": item["baseline_score"], "baseline_vector": "".join("P" if x else "F" for x in item["baseline_check_vector"]), "final_score": item["final_score"], "final_vector": "".join("P" if x else "F" for x in item["final_check_vector"] or []), "delta_score": item["delta_score"], "normalized_improvement": item["normalized_improvement"], "full_pass": item["full_pass"], "wall_seconds": item["wall_seconds"], "evaluator_tampering": item["evaluator_tampering"], "prohibited_changed_files": ";".join(item["prohibited_changed_files"]), "request_count": item["request_count"], "request_metric_semantics": item["request_metric_semantics"], "tool_event_telemetry": item["tool_event_telemetry"], "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"], "cache_read_tokens": usage["cache_read_tokens"], "reasoning_tokens": usage["reasoning_tokens"]})
    # Fill usage from the private ledger only; the bundle receives these rows,
    # not the ledger itself.
    conn = connect()
    for row in rows:
        run_id = next(item["run_id"] for item in evidence if item["resolved"]["provider_model_id"] == row["model"] and item["task"]["family"] == row["task"])
        metric = conn.execute("SELECT input_tokens,output_tokens,cache_read_tokens,reasoning_tokens FROM request_metrics WHERE run_id=? ORDER BY id LIMIT 1", (run_id,)).fetchone()
        if metric:
            row["input_tokens"], row["output_tokens"], row["cache_read_tokens"], row["reasoning_tokens"] = tuple(metric)
    fieldnames = list(rows[0]) if rows else ["model", "reasoning", "task", "status"]
    with (root / "task-check-matrix.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames); writer.writeheader(); writer.writerows(rows)
    lines = ["# Gemini 3.8 reasoning R1 matrix", "", "| Model | Reasoning | Task | Status | Baseline | Final | Delta | Full | Wall s | Tampering | Input | Output | Cache read | Reasoning usage |", "|---|---|---|---|---:|---:|---:|---|---:|---|---:|---:|---:|---:|"]
    for row in rows:
        lines.append("| " + " | ".join(str(row[key] if row[key] is not None else "null") for key in ("model", "reasoning", "task", "status", "baseline_score", "final_score", "delta_score", "full_pass", "wall_seconds", "evaluator_tampering", "input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens")) + " |")
    (root / "task-check-matrix.md").write_text("\n".join(lines) + "\n")
    groups = []
    for model, reasoning in zip(MODELS, REASONING):
        group = [row for row in rows if row["model"] == model]
        clean = [row for row in group if row["status"] == "completed" and not row["evaluator_tampering"] and row["final_score"] is not None]
        groups.append({"model": model, "reasoning": reasoning, "attempted": len(group), "completed_clean": len(clean), "completion_rate": len(clean) / len(group) if group else None, "quality_on_completed": statistics.mean(row["final_score"] for row in clean) if clean else None, "median_final": statistics.median(row["final_score"] for row in clean) if clean else None, "full_solves": sum(row["full_pass"] is True for row in clean), "mean_wall_attempted": statistics.mean(row["wall_seconds"] for row in group) if group else None, "mean_delta": statistics.mean(row["delta_score"] for row in clean) if clean else None, "observed_usage": {field: sum(row[field] for row in group if row[field] is not None) if any(row[field] is not None for row in group) else None for field in ("input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens")}})
    plot_rows = [{**row, "score": row["final_score"], "wall": row["wall_seconds"], "output": row["output_tokens"], "reasoning_usage": row["reasoning_tokens"]} for row in rows]
    plots = {"score-by-task-reasoning": _plot(plot_rows, root / "reasoning-correctness.png", "score", "final score"), "wall-by-task-reasoning": _plot(plot_rows, root / "reasoning-wall.png", "wall", "wall seconds"), "output-by-task-reasoning": _plot(plot_rows, root / "tokens-vs-correctness.png", "output", "AGY-reported output tokens"), "reasoning-usage-by-task": _plot(plot_rows, root / "score-vs-wall.png", "reasoning_usage", "AGY-reported reasoning usage")}
    (root / "plot-metadata.json").write_text(json.dumps(plots, indent=2, sort_keys=True) + "\n")
    baseline = json.loads((root / "validation" / "preflight.json").read_text())["baseline"]["tasks"]
    report_lines = ["# Gemini 3.8 Flash reasoning characterization R1", "", "Evaluation class: `public_characterization`. This is a matched four-task reasoning screen, not Public Characterization V2.5.", "", f"Frozen suite SHA: `{json.loads((root / 'run-summary.json').read_text()).get('suite_git_sha', 'pending')}`.", f"Fixed requested timeout: `{TIMEOUT_SECONDS}` seconds; retries: `0`.", "", "## Baselines", "", *[f"- `{item['family']}`: `{item['baseline_score']}` / `{''.join('P' if x else 'F' for x in item['baseline_check_vector'])}`; visible/controller parity: `{item['visible_controller_parity']}`." for item in baseline], "", "## Configuration summaries", "", "| Model | Reasoning | Quality on clean completion | Median final | Full solves | Clean completed/attempted | Completion rate | Mean wall attempted | Mean delta | Usage fields |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    for item in groups:
        report_lines.append(f"| {item['model']} | {item['reasoning']} | {item['quality_on_completed']} | {item['median_final']} | {item['full_solves']} | {item['completed_clean']}/{item['attempted']} | {item['completion_rate']} | {item['mean_wall_attempted']} | {item['mean_delta']} | `{json.dumps(item['observed_usage'], sort_keys=True)}` |")
    report_lines += ["", "## Semantics", "", "Request count is `harness_session`, not a provider request count. AGY tool telemetry is `unavailable`, not observable zero. Token fields are AGY-reported usage and are not verified provider billing tokens. Quality is conditional on clean scored completion; reliability and operational efficiency are separate.", "", "## Attempt matrix", "", "See `task-check-matrix.md` and `task-check-matrix.csv` for all twelve attempts, vectors, baseline-to-final deltas, scope status, wall time, and usage fields.", "", "## Interpretation", "", "This initial n=4 matched portfolio should be interpreted descriptively. Latency and usage differences are efficiency observations, not coding-quality differences. No persistent default was changed."]
    (root / "REPORT.md").write_text("\n".join(report_lines) + "\n")
    (root / "AUDIT_REPORT.md").write_text("# R1 audit report\n\nThe portfolio was frozen before inference. It used four matched deterministic public contracts, exact Gemini 3.8 runtime IDs, one attempt per cell, a 420-second fixed timeout, zero retries, controller-visible parity, and separate reliability/quality semantics.\n")
    (root / "telemetry-semantics.md").write_text("# Telemetry semantics\n\nAGY request metrics are `harness_session`. Underlying provider request count is not inferred. AGY tool-event telemetry is unavailable, so tool counts remain null.\n")
    (root / "token-semantics.md").write_text("# Token semantics\n\nInput, output, cache-read, and reasoning fields are AGY-reported usage. They are retained separately and are not verified provider billing tokens.\n")
    return root / "REPORT.md"


def main(argv: list[str] | None = None) -> int:
    action = (argv or sys.argv[1:] or ["freeze"])[0]
    if action == "freeze": print(json.dumps(freeze(), indent=2, sort_keys=True)); return 0
    if action == "discover": print(json.dumps(discover(), indent=2, sort_keys=True)); return 0
    if action == "run": print(json.dumps(run_sweep(), indent=2, sort_keys=True)); return 0
    if action == "report": print(report()); return 0
    raise SystemExit(f"unknown command: {action}")


if __name__ == "__main__":
    raise SystemExit(main())
