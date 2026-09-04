"""No-inference validation and one-call V2.4 calibration runner."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import signal
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark.adapters import AntigravityAdapter
from benchmark.provenance import validate_git_identity
from benchmark.review_bundle import create_review_bundle
from benchmark.v2.telemetry import parse_trace
from ekalavya.harness_registry import current_registry, validate_registry
from ekalavya.ledger import (
    connect, finalize_run, record_benchmark_suite, record_benchmark_task,
    record_cost, record_harness, record_request_metric, record_run,
    record_task_attempt,
)

from . import (
    ATTEMPT_TIMEOUT_SECONDS, BASELINE_MAXIMUM, CALIBRATION_CONFIG,
    CALIBRATION_SEED, CHECK_COUNT, EVALUATION_CLASS, EVALUATION_SEED,
    FAMILY, FAMILIES, FEATURE_CLUSTERS, NEW_FEATURE_TARGET, PHASE_CALIBRATION,
    PHASE_COMPARATIVE, SUITE_NAME, SUITE_VERSION,
)
from .evaluate import evaluate
from .generate import TaskInstance, make_instance, materialize, workspace_digest
from .gold_accessibility import audit_tracked_gold_accessibility
from .quality import (
    feature_absence_gate, feature_scaffolding_leakage, prohibited_files,
    surface_metrics, validate_feature_clusters, validate_surface,
)


SOURCE_PATHS = (
    "benchmark/public_characterization_v24/__init__.py",
    "benchmark/public_characterization_v24/generate.py",
    "benchmark/public_characterization_v24/evaluate.py",
    "benchmark/public_characterization_v24/quality.py",
    "benchmark/public_characterization_v24/gold_accessibility.py",
    "benchmark/public_characterization_v24/runner.py",
    "benchmark/provenance.py",
    "benchmark/validation_metadata.py",
    "benchmark/review_bundle.py",
    "benchmark/adapters.py",
    "benchmark/v2/telemetry.py",
    "ekalavya/harness_registry.py",
    "ekalavya/ledger.py",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def git_sha() -> str | None:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root(), capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def state_root() -> Path:
    from ekalavya.ledger import default_state_dir
    root = default_state_dir() / "experiments" / SUITE_NAME
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    return root


def _snapshot(workspace: Path) -> dict[str, str]:
    result = {}
    for path in workspace.rglob("*"):
        if not path.is_file() or path.suffix == ".pyc" or "__pycache__" in path.parts or ".pytest_cache" in path.parts:
            continue
        result[path.relative_to(workspace).as_posix()] = digest(path.read_bytes())
    return result


def _visible_verify(workspace: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [sys.executable, str(workspace / "verifier/verify.py")],
            cwd=workspace, env={**os.environ, "PYTHONPATH": str(workspace)},
            capture_output=True, text=True, timeout=30, check=False,
        )
        payload = json.loads(result.stdout)
        vector = [bool(item) for item in payload["checks"]]
        return {"ok": result.returncode == 0 and len(vector) == CHECK_COUNT, "check_vector": vector, "detail": result.stderr[-1000:]}
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "check_vector": [], "detail": type(exc).__name__}


def _baseline(instance: TaskInstance, workspace: Path) -> dict[str, Any]:
    controller = evaluate(instance, workspace)
    visible = _visible_verify(workspace)
    metrics = surface_metrics(instance.files)
    result = {
        "family": instance.family, "seed": instance.seed, "task_id": instance.task_id,
        "baseline_score": controller["new_feature_score"],
        "baseline_check_vector": controller["check_vector"],
        "old_contract_tests_passed_before": controller["old_contract_tests_passed_after"],
        "visible_check_vector": visible["check_vector"],
        "visible_controller_agree": visible["ok"] and controller["check_vector"] == visible["check_vector"],
        "generated_workspace_hash": workspace_digest(workspace),
        "prompt_hash": digest(instance.prompt.encode()),
        "visible_verifier_hash": instance.visible_verifier_hash,
        "task_spec_hash": instance.task_spec_hash,
        "allowed_edit_manifest_hash": instance.edit_scope_hash,
        "implementation_surface": metrics,
        "feature_absence": feature_absence_gate(instance, repo_root()),
        "feature_scaffolding_leakage": feature_scaffolding_leakage(instance),
    }
    if len(result["baseline_check_vector"]) != CHECK_COUNT:
        raise ValueError("baseline evaluator did not return exactly eight checks")
    return result


def _load_reference(seed: int) -> dict[str, Any] | None:
    path = state_root() / "validation" / "reference-validation.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text())
        return value.get("variants", {}).get(str(seed), value if value.get("seed") == seed else None)
    except (OSError, ValueError):
        return None


def _reference_ok(reference: dict[str, Any] | None, *, seed: int, suite_sha: str | None) -> bool:
    if not reference or reference.get("passed") is not True:
        return False
    if reference.get("suite") != SUITE_NAME or reference.get("version") != SUITE_VERSION or reference.get("seed") != seed or reference.get("suite_git_sha") != suite_sha:
        return False
    if reference.get("gold_accessibility", {}).get("status") != "pass":
        return False
    if reference.get("temporary_reference_repair_deleted") is not True or reference.get("reference_source_retained") is not False:
        return False
    structural = reference.get("structural_validation", {})
    if len(structural.get("feature_clusters", [])) < 4:
        return False
    if not structural.get("single_cluster_gate") or not structural.get("two_cluster_gate") or not structural.get("integration_dependency_gate"):
        return False
    if len(structural.get("distinct_non_full_vectors", [])) < 4:
        return False
    tasks = reference.get("tasks", [])
    return bool(tasks) and all(
        item.get("new_feature_score") == 100.0
        and item.get("check_vector") == [True] * CHECK_COUNT
        and item.get("visible_check_vector") == [True] * CHECK_COUNT
        and item.get("old_contract_tests_passed_after") is True
        and item.get("old_contract_regressions") == 0
        for item in tasks
    )


def _gate_result(instance: TaskInstance, baseline: dict[str, Any], *, reference: dict[str, Any] | None, require_reference: bool, provenance: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "provenance": bool(provenance),
        "gold_accessibility": audit_tracked_gold_accessibility(repo_root())["status"] == "pass",
        "old_contract_baseline": baseline["old_contract_tests_passed_before"] is True,
        "headroom": baseline["baseline_score"] < BASELINE_MAXIMUM and NEW_FEATURE_TARGET[0] <= baseline["baseline_score"] <= NEW_FEATURE_TARGET[1],
        "visible_controller_parity": baseline["visible_controller_agree"] and len(baseline["baseline_check_vector"]) == CHECK_COUNT,
        "deterministic_hashes": baseline["generated_workspace_hash"] == baseline["repeat_workspace_hash"],
        "feature_absence": baseline["feature_absence"]["status"] == "pass",
        "feature_scaffolding_leakage": baseline["feature_scaffolding_leakage"]["status"] == "pass",
        "implementation_surface": validate_surface(baseline["implementation_surface"]),
        "feature_clusters": validate_feature_clusters(),
        "reference_validation": _reference_ok(reference, seed=instance.seed, suite_sha=(provenance or {}).get("git_sha")) if require_reference else "not_required",
    }


def validate_preflight(*, seed: int = CALIBRATION_SEED, phase: str = PHASE_CALIBRATION, require_reference: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {"suite": SUITE_NAME, "version": SUITE_VERSION, "evaluation_class": EVALUATION_CLASS, "phase": phase, "seed": seed, "tasks": []}
    try:
        provenance = validate_git_identity(repo_root(), SOURCE_PATHS)
    except Exception as exc:
        provenance = None
        result["provenance_error"] = str(exc)
    result["provenance"] = provenance
    with tempfile.TemporaryDirectory(prefix="ekalavya-v24-preflight-") as directory:
        root = Path(directory)
        instance = make_instance(FAMILY, seed)
        baseline = _baseline(instance, materialize(instance, root / "first"))
        repeat_instance = make_instance(FAMILY, seed)
        repeat_workspace = materialize(repeat_instance, root / "repeat")
        baseline["repeat_workspace_hash"] = workspace_digest(repeat_workspace)
        baseline["reference_validation_passed"] = None
        result["tasks"].append(baseline)
    reference = _load_reference(seed)
    result["reference_validation"] = reference
    if reference is not None:
        result["tasks"][0]["reference_validation_passed"] = _reference_ok(reference, seed=seed, suite_sha=(provenance or {}).get("git_sha"))
    gates = _gate_result(instance, result["tasks"][0], reference=reference, require_reference=require_reference, provenance=provenance)
    result["gates"] = gates
    result["validation_consistency"] = {
        "ok": all(item.get("reference_validation_passed") is True for item in result["tasks"]) if require_reference else all(item.get("reference_validation_passed") is None for item in result["tasks"]),
        "reason": "consistent",
    }
    gates["validation_consistency"] = result["validation_consistency"]["ok"]
    result["ok"] = all(value is True or value == "not_required" for value in gates.values())
    validation = state_root() / "validation"
    validation.mkdir(parents=True, exist_ok=True, mode=0o700)
    (validation / f"preflight-{phase}-{seed}.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (validation / "preflight.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (state_root() / "VALIDATION_REPORT.md").write_text(f"# {SUITE_NAME} validation\n\nPhase: `{phase}`; seed: `{seed}`; gate: `{str(result['ok']).lower()}`.\n")
    return result


def _terminate(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass


def _attempt(instance: TaskInstance, baseline: dict[str, Any], *, root: Path, conn: Any, suite_id: int, task_db_id: int, harness_id: int, agy_version: str, telemetry: dict[str, Any]) -> dict[str, Any]:
    key = f"{PHASE_CALIBRATION}-{CALIBRATION_CONFIG[0]}-{instance.seed}"
    workspace = root / "workspaces" / key
    materialize(instance, workspace)
    before = _snapshot(workspace)
    run_id = f"{SUITE_NAME}:{uuid.uuid4().hex}"
    started = now()
    requested = {"experiment": SUITE_NAME, "profile": "flash", "provider": "gemini", "provider_model_id": CALIBRATION_CONFIG[0], "model": CALIBRATION_CONFIG[0], "reasoning": CALIBRATION_CONFIG[1], "harness": "agy", "evaluation_class": EVALUATION_CLASS, "phase": PHASE_CALIBRATION, "attempt_timeout_seconds": ATTEMPT_TIMEOUT_SECONDS}
    record_run(conn, run_id, requested, resolved={"provider_model_id": CALIBRATION_CONFIG[0], "reasoning": CALIBRATION_CONFIG[1], "harness": "agy", "harness_version": agy_version}, status="running", evaluation_class=EVALUATION_CLASS, provider="gemini", identity_key=f"gemini:flash:{CALIBRATION_CONFIG[0]}", harness_id=harness_id, billing_mode="subscription", started_at=started)
    evidence_dir = root / "calibration-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    begin = time.monotonic()
    timed_out = False
    code = -1
    stdout = stderr = ""
    try:
        process = subprocess.Popen(AntigravityAdapter(model=CALIBRATION_CONFIG[0], reasoning_effort=CALIBRATION_CONFIG[1]).command(workspace, instance.prompt, evidence_dir / key), cwd=workspace, env={**os.environ, "BENCHMARK_WORKSPACE": str(workspace)}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=ATTEMPT_TIMEOUT_SECONDS)
            code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate(process)
            stdout, stderr = process.communicate()
    except OSError as exc:
        stderr = str(exc)
    wall = time.monotonic() - begin
    after = _snapshot(workspace)
    changed = sorted({name for name in set(before) | set(after) if before.get(name) != after.get(name)})
    prohibited = prohibited_files(changed, instance.edit_scope)
    tamper = bool(prohibited)
    final: dict[str, Any] | None = None
    malformed = False
    if not timed_out and code == 0:
        try:
            final = evaluate(instance, workspace)
            malformed = len(final.get("check_vector", [])) != CHECK_COUNT
        except Exception:
            malformed = True
    requests = parse_trace(stdout)
    status = "explicit_timeout" if timed_out else ("malformed_evaluator" if malformed else ("evaluator_tampering" if tamper else ("completed" if code == 0 else "harness_failure")))
    score = final.get("new_feature_score") if final and not malformed else None
    delta = None if score is None else score - baseline["baseline_score"]
    normalized = None if score is None or baseline["baseline_score"] >= 100 else delta / (100 - baseline["baseline_score"])
    token_values = {field: [getattr(item, field) for item in requests if getattr(item, field) is not None] for field in ("input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens")}
    evidence = {
        "experiment": SUITE_NAME, "evaluation_class": EVALUATION_CLASS, "phase": PHASE_CALIBRATION, "run_id": run_id, "requested": requested,
        "resolved": {"provider_model_id": CALIBRATION_CONFIG[0], "reasoning": CALIBRATION_CONFIG[1], "harness": "agy", "harness_version": agy_version}, "started_at": started, "ended_at": now(), "wall_seconds": wall, "exit_code": code, "timed_out": timed_out, "status": status,
        "changed_files": changed, "evaluator_tampering": tamper, "prohibited_changed_files": prohibited,
        "baseline_score": baseline["baseline_score"], "baseline_check_vector": baseline["baseline_check_vector"], "final_score": score, "final_check_vector": final.get("check_vector") if final and not malformed else None, "new_feature_score": score, "delta_score": delta, "normalized_improvement": normalized,
        "full_pass": final.get("full_pass") if final and not malformed and not tamper else False if final and not malformed else None, "old_contract_tests_passed_before": baseline["old_contract_tests_passed_before"], "old_contract_tests_passed_after": final.get("old_contract_tests_passed_after") if final and not malformed else None, "old_contract_regressions": final.get("old_contract_regressions") if final and not malformed else None,
        "request_count": len(requests) or None, "request_metric_semantics": telemetry.get("request_metric_semantics"), "tool_event_telemetry": telemetry.get("tool_event_telemetry"), "tool_events": None, "token_metric_semantics": telemetry.get("token_metric_semantics"),
        "input_tokens": sum(token_values["input_tokens"]) if token_values["input_tokens"] else None, "output_tokens": sum(token_values["output_tokens"]) if token_values["output_tokens"] else None, "cache_read_tokens": sum(token_values["cache_read_tokens"]) if token_values["cache_read_tokens"] else None, "reasoning_tokens": sum(token_values["reasoning_tokens"]) if token_values["reasoning_tokens"] else None,
        "task": {"suite": SUITE_NAME, "version": SUITE_VERSION, "family": instance.family, "task_id": instance.task_id, "seed": instance.seed, "generated_workspace_hash": baseline["generated_workspace_hash"], "prompt_hash": baseline["prompt_hash"], "visible_verifier_hash": baseline["visible_verifier_hash"], "task_spec_hash": baseline["task_spec_hash"], "allowed_edit_manifest_hash": baseline["allowed_edit_manifest_hash"]}, "suite_git_sha": git_sha(), "assessment": final,
    }
    path = evidence_dir / f"{key}.json"
    path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    record_task_attempt(conn, run_id, task_id=task_db_id, score=score, public_score=score, invariant_score=score, scope_compliant=not tamper, wall_seconds=wall, baseline_score=baseline["baseline_score"], baseline_check_vector=baseline["baseline_check_vector"], final_check_vector=evidence["final_check_vector"], delta_score=delta, normalized_improvement=normalized, evaluator_tampering=tamper, prohibited_changed_files=prohibited, metadata=evidence)
    for request in requests:
        record_request_metric(conn, run_id, request.json())
    record_cost(conn, run_id, billing_mode="subscription", cost_source="unavailable: subscription route", input_tokens=evidence["input_tokens"], output_tokens=evidence["output_tokens"], cached_input_tokens=evidence["cache_read_tokens"], reasoning_tokens=evidence["reasoning_tokens"])
    finalize_run(conn, run_id, ended_at=evidence["ended_at"], status=status, raw_evidence_path=str(path), raw_evidence_sha256=digest(path.read_bytes()))
    return evidence


def _materialize_public(instance: TaskInstance, root: Path) -> None:
    for directory in ("task-specifications", "verifier-contracts", "edit-scopes", "baseline-task-snapshots"):
        (root / directory / instance.family).mkdir(parents=True, exist_ok=True)
    (root / "task-specifications" / instance.family / "README.md").write_text(instance.files["README.md"])
    (root / "task-specifications" / instance.family / "specification.json").write_text(json.dumps(instance.specification, indent=2, sort_keys=True) + "\n")
    (root / "verifier-contracts" / instance.family / "contract.py").write_text(instance.files["verifier/contract.py"])
    (root / "verifier-contracts" / instance.family / "verify.py").write_text(instance.files["verifier/verify.py"])
    (root / "edit-scopes" / instance.family / "allowed-edit-manifest.json").write_text(json.dumps(instance.edit_scope, indent=2, sort_keys=True) + "\n")
    for name, value in instance.files.items():
        if name.startswith((".ekalavya/", "verifier/")):
            continue
        path = root / "baseline-task-snapshots" / instance.family / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value)


def _rows(root: Path) -> list[dict[str, Any]]:
    rows = []
    for directory in (root / "calibration-evidence", root / "evidence"):
        if directory.is_dir():
            rows.extend(json.loads(path.read_text()) for path in sorted(directory.glob("*.json")))
    return rows


def _report_timeout(rows: list[dict[str, Any]]) -> int:
    values = {int(row.get("requested", {}).get("attempt_timeout_seconds")) for row in rows if row.get("requested", {}).get("attempt_timeout_seconds") is not None}
    return values.pop() if len(values) == 1 else ATTEMPT_TIMEOUT_SECONDS


def report(root: Path | None = None) -> dict[str, Any]:
    root = (root or state_root()).resolve()
    rows = _rows(root)
    timeout = _report_timeout(rows)
    fields = ["model", "reasoning", "phase", "task", "status", "baseline_score", "baseline_check_vector", "final_score", "final_check_vector", "delta_score", "normalized_improvement", "old_contract_tests_passed_before", "old_contract_tests_passed_after", "old_contract_regressions", "full_pass", "evaluator_tampering", "prohibited_changed_files", "wall_seconds", "input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens"]
    with (root / "task-check-matrix.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            vector = row.get("final_check_vector")
            writer.writerow({"model": row["resolved"]["provider_model_id"], "reasoning": row["resolved"]["reasoning"], "phase": row["phase"], "task": row["task"]["family"], "status": row["status"], "baseline_score": row["baseline_score"], "baseline_check_vector": "".join("P" if item else "F" for item in row["baseline_check_vector"]), "final_score": row.get("final_score"), "final_check_vector": "".join("P" if item else "F" for item in vector) if vector else None, "delta_score": row.get("delta_score"), "normalized_improvement": row.get("normalized_improvement"), "old_contract_tests_passed_before": row.get("old_contract_tests_passed_before"), "old_contract_tests_passed_after": row.get("old_contract_tests_passed_after"), "old_contract_regressions": row.get("old_contract_regressions"), "full_pass": row.get("full_pass"), "evaluator_tampering": row.get("evaluator_tampering"), "prohibited_changed_files": json.dumps(row.get("prohibited_changed_files", [])), "wall_seconds": row.get("wall_seconds"), "input_tokens": row.get("input_tokens"), "output_tokens": row.get("output_tokens"), "cache_read_tokens": row.get("cache_read_tokens"), "reasoning_tokens": row.get("reasoning_tokens")})
    lines = [f"# {SUITE_NAME} task matrix", "", "Calibration is excluded from any future comparison statistics.", ""]
    for row in rows:
        baseline = "".join("P" if item else "F" for item in row["baseline_check_vector"])
        final = "".join("P" if item else "F" for item in row.get("final_check_vector") or []) or "—"
        lines.append(f"- `{row['phase']}` / `{row['resolved']['provider_model_id']}` / `{row['task']['family']}`: `{row['status']}`; baseline `{baseline}`; final `{final}`; score `{row.get('final_score', '—')}`; delta `{row.get('delta_score', '—')}`.")
    (root / "task-check-matrix.md").write_text("\n".join(lines) + "\n")
    calibration = [row for row in rows if row["phase"] == PHASE_CALIBRATION]
    useful = bool(calibration and calibration[0].get("status") == "completed" and calibration[0].get("final_score") not in (None, calibration[0].get("baseline_score"), 100.0) and calibration[0].get("old_contract_regressions") == 0)
    (root / "calibration-summary.json").write_text(json.dumps({"phase": PHASE_CALIBRATION, "attempted": len(calibration), "completed": sum(row["status"] == "completed" for row in calibration), "model": CALIBRATION_CONFIG[0], "reasoning": CALIBRATION_CONFIG[1], "useful": useful, "comparison_ran": False}, indent=2, sort_keys=True) + "\n")
    observations = [row for row in rows if row.get("status") == "completed" and row.get("final_score") is not None]
    plots: dict[str, Any] = {}
    if observations:
        import matplotlib.pyplot as plt
        for filename, xkey, xlabel in (("baseline-vs-final.png", "baseline_score", "baseline new-feature score"), ("final-vs-wall.png", "wall_seconds", "wall seconds"), ("final-vs-tokens.png", "output_tokens", "AGY-reported output tokens")):
            plt.figure(figsize=(8, 5))
            plt.scatter([row.get(xkey) or 0 for row in observations], [row["final_score"] for row in observations])
            plt.xlabel(xlabel); plt.ylabel("final new-feature score"); plt.tight_layout(); plt.savefig(root / filename); plt.close()
            plots[filename] = {"status": "created", "observations": len(observations), "plot_type": "scatter"}
        plt.figure(figsize=(8, 5)); plt.bar([f"{row['resolved']['provider_model_id']} / {row['task']['family']}" for row in observations], [row.get("delta_score") or 0 for row in observations]); plt.xticks(rotation=25, ha="right"); plt.ylabel("delta new-feature score"); plt.tight_layout(); plt.savefig(root / "delta-by-configuration.png"); plt.close(); plots["delta-by-configuration.png"] = {"status": "created", "observations": len(observations), "plot_type": "bar"}
    (root / "plot-metadata.json").write_text(json.dumps(plots, indent=2, sort_keys=True) + "\n")
    (root / "telemetry-semantics.md").write_text("# AGY telemetry semantics\n\nAGY request metrics are recorded as `harness_session`, not verified provider model requests. Tool event telemetry is `unavailable`, not observable zero.\n")
    (root / "token-semantics.md").write_text("# Token semantics\n\nInput, output, cache-read, and reasoning fields are AGY-reported usage, not verified provider billing tokens. Values are retained separately and are not treated as billing totals.\n")
    (root / "REPORT.md").write_text(f"# {SUITE_NAME}\n\nEvaluation class: `{EVALUATION_CLASS}`. Actual requested/report timeout: `{timeout}` seconds. Calibration attempts: `{len(calibration)}`. Comparative characterization: `not run`.\n\nV2.3 audit note: retained execution evidence consistently records 420 seconds; the stale 900-second summary came from an older plan/default and was not an executed V2.3 budget. V2.3 is preserved as valid, saturated, feature-scaffolding-heavy calibration evidence.\n\nV2.4 uses a mature synthetic correct baseline plus a novel owner-scoped named-report-bookmark feature. Its public issue/verifier remain behavioral; the controller retains structural and absence gates.\n")
    (root / "AUDIT_REPORT.md").write_text("# Public Characterization V2.4 audit\n\nV2.4 is a repository-scale feature-integration calibration. Calibration is excluded from model-ranking statistics. No comparative run is authorized by this task.\n")
    (root / "VALIDATION_REPORT.md").write_text((root / "validation/preflight.json").read_text() if (root / "validation/preflight.json").is_file() else "Validation metadata not yet generated.\n")
    validation = root / "validation"
    validation.mkdir(parents=True, exist_ok=True)
    preflight = {}
    if (validation / "preflight.json").is_file():
        try:
            preflight = json.loads((validation / "preflight.json").read_text())
        except (OSError, ValueError):
            preflight = {}
    task = (preflight.get("tasks") or [{}])[0]
    (validation / "implementation-surface.json").write_text(json.dumps(task.get("implementation_surface", {}), indent=2, sort_keys=True) + "\n")
    (validation / "feature-absence.json").write_text(json.dumps(task.get("feature_absence", {}), indent=2, sort_keys=True) + "\n")
    (validation / "feature-scaffolding-leakage.json").write_text(json.dumps(task.get("feature_scaffolding_leakage", {}), indent=2, sort_keys=True) + "\n")
    reference = preflight.get("reference_validation") or {}
    (validation / "structural-validation-summary.json").write_text(json.dumps(reference.get("structural_validation", {}), indent=2, sort_keys=True) + "\n")
    (validation / "gold-accessibility.json").write_text(json.dumps(reference.get("gold_accessibility", {}), indent=2, sort_keys=True) + "\n")
    (validation / "old-contract-summary.json").write_text(json.dumps({"before": task.get("old_contract_tests_passed_before"), "calibration_after": [(row.get("old_contract_tests_passed_after"), row.get("old_contract_regressions")) for row in rows]}, indent=2, sort_keys=True) + "\n")
    return {"timeout_seconds": timeout, "calibration_attempts": len(calibration), "calibration_useful": useful, "comparative_ran": False, "plots": plots}


def _record_suite(conn: Any, instance: TaskInstance, baseline: dict[str, Any], provenance: dict[str, Any], reference: dict[str, Any]) -> tuple[int, int]:
    suite_id = record_benchmark_suite(conn, SUITE_NAME, EVALUATION_CLASS, SUITE_VERSION, git_sha=provenance["git_sha"], evaluation_class=EVALUATION_CLASS, metadata={"family": FAMILY, "calibration_seed": CALIBRATION_SEED, "evaluation_seed_reserved": EVALUATION_SEED, "attempt_timeout_seconds": ATTEMPT_TIMEOUT_SECONDS, "implementation_surface": baseline["implementation_surface"], "calibration_excluded_from_rankings": True})
    task_id = record_benchmark_task(conn, suite_id, family=FAMILY, task_id=instance.task_id, variant_seed=str(instance.seed), content_hash=digest(json.dumps(instance.files, sort_keys=True).encode()), prompt_hash=baseline["prompt_hash"], evaluator_hash=baseline["visible_verifier_hash"], baseline_score=baseline["baseline_score"], baseline_check_vector=baseline["baseline_check_vector"], task_spec_hash=baseline["task_spec_hash"], allowed_edit_manifest_hash=baseline["allowed_edit_manifest_hash"], reference_validation_passed=True, reference_validation_at=reference.get("validation_timestamp"))
    return suite_id, task_id


def pilot() -> dict[str, Any]:
    gate = validate_preflight(seed=CALIBRATION_SEED, phase=PHASE_CALIBRATION, require_reference=True)
    if not gate["ok"]:
        raise RuntimeError("V2.4 calibration no-inference gates failed; no model started")
    root = state_root()
    if list((root / "calibration-evidence").glob("*.json")) or list((root / "evidence").glob("*.json")):
        raise RuntimeError("V2.4 evidence already exists; retry prohibited")
    instance = make_instance(FAMILY, CALIBRATION_SEED)
    baseline = gate["tasks"][0]
    provenance = gate["provenance"]
    registry = current_registry(); validate_registry(registry)
    agy = next(item for item in registry if item["name"] == "agy")
    conn = connect()
    observed_version = agy.get("observed_version") or agy["version"]
    harness_id = record_harness(conn, "agy", version=observed_version, adapter_version="benchmark.public_characterization_v24.runner", transport="agy", capabilities=agy["capabilities"], telemetry=agy["telemetry"], eligibility=agy["eligibility"], evidence_label="public_characterization_non_adversarial", observed_at=now())
    _materialize_public(instance, root)
    discovery = {"experiment": SUITE_NAME, "evaluation_class": EVALUATION_CLASS, "suite_git_sha": provenance["git_sha"], "calibration_seed": CALIBRATION_SEED, "evaluation_seed_reserved": EVALUATION_SEED, "calibration_configuration": {"model": CALIBRATION_CONFIG[0], "reasoning": CALIBRATION_CONFIG[1]}, "comparison_configurations_reserved": [], "attempt_timeout_seconds": ATTEMPT_TIMEOUT_SECONDS, "agy_version": observed_version, "telemetry": agy["telemetry"]}
    (root / "discovery.json").write_text(json.dumps(discovery, indent=2, sort_keys=True) + "\n")
    suite_id, task_id = _record_suite(conn, instance, baseline, provenance, gate["reference_validation"])
    evidence = _attempt(instance, baseline, root=root, conn=conn, suite_id=suite_id, task_db_id=task_id, harness_id=harness_id, agy_version=observed_version, telemetry=agy["telemetry"])
    summary = {"experiment": SUITE_NAME, "evaluation_class": EVALUATION_CLASS, "suite_git_sha": provenance["git_sha"], "calibration_seed": CALIBRATION_SEED, "evaluation_seed_reserved": EVALUATION_SEED, "calibration_attempts": 1, "comparative_attempts": 0, "attempts": 1, "completed": int(evidence["status"] == "completed"), "harness_failure": int(evidence["status"] == "harness_failure"), "explicit_timeout": int(evidence["status"] == "explicit_timeout"), "evaluator_tampering": int(evidence["status"] == "evaluator_tampering"), "calibration_excluded_from_rankings": True, "comparative_ran": False}
    (root / "run-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    report(root)
    create_review_bundle(SUITE_NAME, state_dir=root)
    return summary


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if action == "validate":
        result = validate_preflight(seed=CALIBRATION_SEED, phase=PHASE_CALIBRATION, require_reference="--require-reference" in sys.argv)
        print(json.dumps(result, indent=2, sort_keys=True)); raise SystemExit(0 if result["ok"] else 1)
    if action == "pilot":
        print(json.dumps(pilot(), indent=2, sort_keys=True)); raise SystemExit(0)
    if action == "report":
        print(json.dumps(report(), indent=2, sort_keys=True)); raise SystemExit(0)
    raise SystemExit(f"unknown action {action}")
