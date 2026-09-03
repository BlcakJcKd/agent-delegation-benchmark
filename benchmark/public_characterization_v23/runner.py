"""V2.3 task validation and bounded feature-integration characterization."""
from __future__ import annotations

import csv
import fnmatch
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

from benchmark.adapters import AntigravityAdapter
from benchmark.provenance import validate_git_identity
from benchmark.v2.telemetry import parse_trace
from benchmark.validation_metadata import validation_consistency
from ekalavya.harness_registry import current_registry, validate_registry
from ekalavya.ledger import connect, finalize_run, record_benchmark_suite, record_benchmark_task, record_cost, record_harness, record_request_metric, record_run, record_task_attempt

from . import ATTEMPT_TIMEOUT_SECONDS, BASELINE_MAXIMUM, CALIBRATION_CONFIG, CALIBRATION_SEED, CHECK_COUNT, COMPARISON_CONFIGURATIONS, EVALUATION_CLASS, EVALUATION_SEED, FAMILIES, NEW_FEATURE_TARGET, PHASE_CALIBRATION, PHASE_COMPARATIVE, SUITE_NAME, SUITE_VERSION
from .evaluate import evaluate
from .generate import TaskInstance, make_instance, materialize, sha256_json, workspace_digest
from .gold_accessibility import audit_tracked_gold_accessibility

SOURCE_PATHS = (
    "benchmark/public_characterization_v23/__init__.py",
    "benchmark/public_characterization_v23/generate.py",
    "benchmark/public_characterization_v23/evaluate.py",
    "benchmark/public_characterization_v23/runner.py",
    "benchmark/public_characterization_v23/gold_accessibility.py",
    "benchmark/validation_metadata.py",
    "benchmark/v2/telemetry.py",
    "benchmark/adapters.py",
    "benchmark/provenance.py",
    "ekalavya/harness_registry.py",
    "ekalavya/ledger.py",
    "benchmark/review_bundle.py",
)

FEATURE_CLUSTERS = [
    {"id": "snapshot_state", "domains": ["repository version", "immutable state capture"]},
    {"id": "snapshot_query_cache", "domains": ["catalogue lookup", "cache/index separation"]},
    {"id": "snapshot_api_compatibility", "domains": ["new API", "old caller compatibility"]},
    {"id": "snapshot_serialization", "domains": ["codec", "restoration"]},
    {"id": "snapshot_reporting_orchestration", "domains": ["report composition", "service propagation"]},
]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def state_root() -> Path:
    from ekalavya.ledger import default_state_dir
    root = default_state_dir() / "experiments" / SUITE_NAME
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    return root


def _snapshot(workspace: Path) -> dict[str, str]:
    return {p.relative_to(workspace).as_posix(): digest(p.read_bytes()) for p in workspace.rglob("*") if p.is_file() and p.suffix != ".pyc" and "__pycache__" not in p.parts and ".pytest_cache" not in p.parts}


def _match(path: str, pattern: str) -> bool:
    return fnmatch.fnmatch(path, pattern) or ("**/" in pattern and fnmatch.fnmatch(path, pattern.replace("**/", "")))


def prohibited_files(changes: list[str], scope: dict) -> list[str]:
    return [p for p in changes if not any(part in {"__pycache__", ".pytest_cache"} for part in Path(p).parts) and Path(p).suffix != ".pyc" and not any(_match(p, pattern) for pattern in scope.get("editable", []))]


def _sloc_and_graph(instance: TaskInstance) -> dict:
    sloc = 0
    modules = []
    graph = {}
    for name, source in instance.files.items():
        if not name.endswith(".py") or name.startswith("tests/") or name.startswith("verifier/") or Path(name).name == "__init__.py":
            continue
        modules.append(name[:-3].replace("/", "."))
        sloc += sum(1 for line in source.splitlines() if line.strip() and not line.lstrip().startswith("#"))
        graph[name] = [line.strip() for line in source.splitlines() if line.strip().startswith(("from ", "import "))]
    return {"substantive_sloc": sloc, "meaningful_module_count": len(modules), "dependency_graph": graph}


def _visible_verify(workspace: Path) -> dict:
    try:
        result = subprocess.run([sys.executable, str(workspace / "verifier/verify.py")], cwd=workspace, env={**os.environ, "PYTHONPATH": str(workspace)}, text=True, capture_output=True, timeout=30, check=False)
        payload = json.loads(result.stdout)
        vector = [bool(x) for x in payload["checks"]]
        return {"ok": result.returncode == 0 and len(vector) == CHECK_COUNT, "check_vector": vector, "detail": result.stderr[-1000:]}
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "check_vector": [], "detail": type(exc).__name__}


def _baseline(instance: TaskInstance, workspace: Path) -> dict:
    controller = evaluate(instance, workspace)
    visible = _visible_verify(workspace)
    if len(controller["check_vector"]) != CHECK_COUNT:
        raise ValueError("baseline evaluator did not return eight checks")
    return {
        "family": instance.family, "seed": instance.seed, "task_id": instance.task_id,
        "baseline_score": controller["new_feature_score"], "baseline_check_vector": controller["check_vector"],
        "old_contract_tests_passed_before": controller["old_contract_tests_passed_after"],
        "visible_check_vector": visible["check_vector"], "visible_controller_agree": visible["ok"] and controller["check_vector"] == visible["check_vector"],
        "generated_workspace_hash": workspace_digest(workspace), "prompt_hash": digest(instance.prompt.encode()),
        "visible_verifier_hash": instance.visible_verifier_hash, "task_spec_hash": instance.task_spec_hash,
        "allowed_edit_manifest_hash": instance.edit_scope_hash, "implementation_surface": _sloc_and_graph(instance),
    }


def _load_reference(seed: int):
    path = state_root() / "validation" / "reference-validation.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text())
        return value.get("variants", {}).get(str(seed)) if "variants" in value else None
    except (OSError, ValueError):
        return None


def _reference_ok(result: dict) -> bool:
    reference = result.get("reference_validation")
    if not reference or reference.get("passed") is not True or reference.get("suite") != SUITE_NAME or reference.get("version") != SUITE_VERSION or reference.get("seed") != result["seed"] or reference.get("suite_git_sha") != result["provenance"].get("git_sha"):
        return False
    if reference.get("gold_accessibility", {}).get("status") != "pass" or reference.get("temporary_reference_repair_deleted") is not True or reference.get("reference_source_retained") is not False:
        return False
    structural = reference.get("structural_validation", {})
    if len(structural.get("feature_clusters", [])) < 4 or not structural.get("single_cluster_gate") or not structural.get("integration_dependency_gate") or len(structural.get("distinct_non_full_vectors", [])) < 4:
        return False
    items = {item.get("family"): item for item in reference.get("tasks", [])}
    return all(item.get("new_feature_score") == 100.0 and item.get("check_vector") == [True] * CHECK_COUNT and item.get("old_contract_tests_passed_after") is True and item.get("old_contract_regressions") == 0 for item in items.values()) and bool(items)


def validate_preflight(*, seed: int, phase: str, require_reference: bool = False) -> dict:
    result = {"suite": SUITE_NAME, "version": SUITE_VERSION, "evaluation_class": EVALUATION_CLASS, "phase": phase, "seed": seed, "tasks": [], "provenance": None, "reference_validation": None}
    try:
        result["provenance"] = validate_git_identity(Path(__file__).resolve().parents[2], SOURCE_PATHS)
    except Exception as exc:
        result["provenance_error"] = str(exc)
    result["gold_accessibility"] = audit_tracked_gold_accessibility(Path(__file__).resolve().parents[2])
    with tempfile.TemporaryDirectory(prefix="ekalavya-v23-preflight-") as directory:
        base = Path(directory)
        instance = make_instance("P1_snapshot_inventory", seed)
        workspace = materialize(instance, base / "P1")
        baseline = _baseline(instance, workspace)
        repeat = materialize(make_instance("P1_snapshot_inventory", seed), base / "repeat")
        baseline["headroom_passed"] = baseline["baseline_score"] < BASELINE_MAXIMUM and NEW_FEATURE_TARGET[0] <= baseline["baseline_score"] <= NEW_FEATURE_TARGET[1]
        baseline["deterministic_hash_passed"] = baseline["generated_workspace_hash"] == workspace_digest(repeat)
        baseline["reference_validation_passed"] = None
        result["tasks"].append(baseline)
    reference = _load_reference(seed)
    if reference is not None:
        result["reference_validation"] = reference
        result["tasks"][0]["reference_validation_passed"] = _reference_ok(result)
    result["gates"] = {
        "provenance": bool(result.get("provenance")),
        "gold_accessibility": result["gold_accessibility"].get("status") == "pass",
        "old_contract_baseline": all(item["old_contract_tests_passed_before"] for item in result["tasks"]),
        "headroom": all(item["headroom_passed"] for item in result["tasks"]),
        "implementation_surface": all(250 <= item["implementation_surface"]["substantive_sloc"] <= 600 and 8 <= item["implementation_surface"]["meaningful_module_count"] <= 15 for item in result["tasks"]),
        "visible_controller_parity": all(item["visible_controller_agree"] and len(item["baseline_check_vector"]) == CHECK_COUNT for item in result["tasks"]),
        "deterministic_hashes": all(item["deterministic_hash_passed"] for item in result["tasks"]),
        "feature_clusters": len(FEATURE_CLUSTERS) >= 4,
        "reference_validation": _reference_ok(result) if require_reference else "not_required",
    }
    result["validation_consistency"] = validation_consistency(result, reference_required=require_reference, check_count=CHECK_COUNT)
    result["gates"]["validation_consistency"] = result["validation_consistency"]["ok"]
    result["ok"] = all(value is True or value == "not_required" for value in result["gates"].values())
    validation_dir = state_root() / "validation"; validation_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    (validation_dir / f"preflight-{phase}-{seed}.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (validation_dir / "preflight.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (state_root() / "VALIDATION_REPORT.md").write_text(f"V2.3 {phase} seed {seed} gate={str(result['ok']).lower()}\n")
    return result


def _terminate(process):
    try:
        os.killpg(process.pid, signal.SIGTERM); process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try: os.killpg(process.pid, signal.SIGKILL)
        except OSError: pass


def _attempt(instance: TaskInstance, baseline: dict, model: str, reasoning: str, phase: str, root: Path, conn, suite_id: int, task_db_id: int, harness_id: int, agy_version: str, telemetry: dict) -> dict:
    key = f"{phase}-{model}-{instance.seed}"; workspace = root / "workspaces" / key; materialize(instance, workspace); before = _snapshot(workspace)
    run_id = f"{SUITE_NAME}:{uuid.uuid4().hex}"; started = now(); requested = {"experiment": SUITE_NAME, "profile": "flash", "provider": "gemini", "provider_model_id": model, "model": model, "reasoning": reasoning, "harness": "agy", "evaluation_class": EVALUATION_CLASS, "phase": phase, "attempt_timeout_seconds": ATTEMPT_TIMEOUT_SECONDS}
    record_run(conn, run_id, requested, resolved={"provider_model_id": model, "reasoning": reasoning, "harness": "agy", "harness_version": agy_version}, status="running", evaluation_class=EVALUATION_CLASS, provider="gemini", identity_key=f"gemini:flash:{model}", harness_id=harness_id, billing_mode="subscription", started_at=started)
    evidence_dir = root / ("calibration-evidence" if phase == PHASE_CALIBRATION else "evidence"); evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700); begin = time.monotonic(); timed_out = False; code = -1; stdout = stderr = ""
    try:
        process = subprocess.Popen(AntigravityAdapter(model=model, reasoning_effort=reasoning).command(workspace, instance.prompt, evidence_dir / key), cwd=workspace, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, "BENCHMARK_WORKSPACE": str(workspace)}, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=ATTEMPT_TIMEOUT_SECONDS); code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True; _terminate(process); stdout, stderr = process.communicate()
    except OSError as exc:
        stderr = str(exc)
    wall = time.monotonic() - begin; changed = sorted({name for name in set(before) | set(_snapshot(workspace)) if before.get(name) != _snapshot(workspace).get(name)}); prohibited = prohibited_files(changed, instance.edit_scope); tamper = bool(prohibited); final = None; malformed = False
    if not timed_out and code == 0:
        try:
            final = evaluate(instance, workspace); malformed = len(final["check_vector"]) != CHECK_COUNT
        except Exception:
            malformed = True
    requests = parse_trace(stdout); status = "explicit_timeout" if timed_out else ("malformed_evaluator" if malformed else ("evaluator_tampering" if tamper else ("completed" if code == 0 else "harness_failure")))
    score = final["new_feature_score"] if final and not malformed else None; delta = None if score is None else score - baseline["baseline_score"]; normalized = None if score is None else (delta / (100 - baseline["baseline_score"]) if baseline["baseline_score"] < 100 else None)
    token_values = {field: [getattr(item, field) for item in requests if getattr(item, field) is not None] for field in ("input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens")}
    evidence = {
        "experiment": SUITE_NAME, "evaluation_class": EVALUATION_CLASS, "phase": phase,
        "run_id": run_id, "requested": requested,
        "resolved": {"provider_model_id": model, "reasoning": reasoning, "harness": "agy", "harness_version": agy_version},
        "started_at": started, "ended_at": now(), "wall_seconds": wall, "exit_code": code,
        "timed_out": timed_out, "status": status, "changed_files": changed,
        "evaluator_tampering": tamper, "prohibited_changed_files": prohibited,
        "baseline_score": baseline["baseline_score"], "baseline_check_vector": baseline["baseline_check_vector"],
        "final_score": score, "final_check_vector": final["check_vector"] if final and not malformed else None,
        "new_feature_score": score, "delta_score": delta, "normalized_improvement": normalized,
        "full_pass": final["full_pass"] if final and not malformed and not tamper else False if final and not malformed else None,
        "old_contract_tests_passed_before": baseline["old_contract_tests_passed_before"],
        "old_contract_tests_passed_after": final["old_contract_tests_passed_after"] if final and not malformed else None,
        "old_contract_regressions": final["old_contract_regressions"] if final and not malformed else None,
        "request_count": len(requests) or None, "request_metric_semantics": telemetry.get("request_metric_semantics"),
        "tool_event_telemetry": telemetry.get("tool_event_telemetry"), "tool_events": None,
        "token_metric_semantics": telemetry.get("token_metric_semantics"),
        "input_tokens": sum(token_values["input_tokens"]) if token_values["input_tokens"] else None,
        "output_tokens": sum(token_values["output_tokens"]) if token_values["output_tokens"] else None,
        "cache_read_tokens": sum(token_values["cache_read_tokens"]) if token_values["cache_read_tokens"] else None,
        "reasoning_tokens": sum(token_values["reasoning_tokens"]) if token_values["reasoning_tokens"] else None,
        "task": {"family": instance.family, "task_id": instance.task_id, "seed": instance.seed,
                 "generated_workspace_hash": baseline["generated_workspace_hash"], "prompt_hash": baseline["prompt_hash"],
                 "visible_verifier_hash": baseline["visible_verifier_hash"], "task_spec_hash": baseline["task_spec_hash"],
                 "allowed_edit_manifest_hash": baseline["allowed_edit_manifest_hash"]},
        "suite_git_sha": git_sha(), "assessment": final,
    }
    path = evidence_dir / f"{key}.json"; path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n"); record_task_attempt(conn, run_id, task_id=task_db_id, score=score, public_score=score, invariant_score=score, scope_compliant=not tamper, wall_seconds=wall, baseline_score=baseline["baseline_score"], baseline_check_vector=baseline["baseline_check_vector"], final_check_vector=evidence["final_check_vector"], delta_score=delta, normalized_improvement=normalized, evaluator_tampering=tamper, prohibited_changed_files=prohibited, metadata=evidence)
    for request in requests: record_request_metric(conn, run_id, request.json())
    record_cost(conn, run_id, billing_mode="subscription", cost_source="unavailable: subscription route", input_tokens=evidence["input_tokens"], output_tokens=evidence["output_tokens"], cached_input_tokens=evidence["cache_read_tokens"], reasoning_tokens=evidence["reasoning_tokens"]); finalize_run(conn, run_id, ended_at=evidence["ended_at"], status=status, raw_evidence_path=str(path), raw_evidence_sha256=digest(path.read_bytes())); return evidence


def _rows(root: Path, phase: str | None = None) -> list[dict]:
    directory = root / ("calibration-evidence" if phase == PHASE_CALIBRATION else "evidence")
    return [json.loads(path.read_text()) for path in sorted(directory.glob("*.json"))] if directory.is_dir() else []


def _materialize_public(instance: TaskInstance, root: Path) -> None:
    for base in ("task-specifications", "verifier-contracts", "edit-scopes", "baseline-task-snapshots"):
        (root / base / instance.family).mkdir(parents=True, exist_ok=True)
    (root / "task-specifications" / instance.family / "README.md").write_text(instance.files["README.md"])
    (root / "task-specifications" / instance.family / "specification.json").write_text(json.dumps(instance.specification, indent=2, sort_keys=True) + "\n")
    (root / "verifier-contracts" / instance.family / "contract.py").write_text(instance.files["verifier/contract.py"])
    (root / "verifier-contracts" / instance.family / "verify.py").write_text(instance.files["verifier/verify.py"])
    (root / "edit-scopes" / instance.family / "allowed-edit-manifest.json").write_text(json.dumps(instance.edit_scope, indent=2, sort_keys=True) + "\n")
    for name, value in instance.files.items():
        if not name.startswith((".ekalavya/", "verifier/")):
            path = root / "baseline-task-snapshots" / instance.family / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(value)


def report(root: Path | None = None) -> dict:
    root = (root or state_root()).resolve(); calibration = _rows(root, PHASE_CALIBRATION); comparative = _rows(root); allrows = calibration + comparative
    fields = ["model", "reasoning", "phase", "task", "status", "baseline_score", "baseline_check_vector", "new_feature_score", "final_score", "final_check_vector"] + [f"check_{i}" for i in range(1, 9)] + ["delta_score", "normalized_improvement", "old_contract_tests_passed_before", "old_contract_tests_passed_after", "old_contract_regressions", "full_pass", "evaluator_tampering", "prohibited_changed_files", "wall_seconds", "input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens"]
    with (root / "task-check-matrix.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields); writer.writeheader()
        for row in allrows:
            vector = row.get("final_check_vector"); writer.writerow({"model": row["resolved"]["provider_model_id"], "reasoning": row["resolved"]["reasoning"], "phase": row["phase"], "task": row["task"]["family"], "status": row["status"], "baseline_score": row["baseline_score"], "baseline_check_vector": "".join("P" if x else "F" for x in row["baseline_check_vector"]), "new_feature_score": row.get("new_feature_score"), "final_score": row.get("final_score"), "final_check_vector": "".join("P" if x else "F" for x in vector) if vector else None, **{f"check_{i}": ("P" if x else "F") if vector else None for i, x in enumerate(vector or [], 1)}, "delta_score": row.get("delta_score"), "normalized_improvement": row.get("normalized_improvement"), "old_contract_tests_passed_before": row.get("old_contract_tests_passed_before"), "old_contract_tests_passed_after": row.get("old_contract_tests_passed_after"), "old_contract_regressions": row.get("old_contract_regressions"), "full_pass": row.get("full_pass"), "evaluator_tampering": row.get("evaluator_tampering"), "prohibited_changed_files": json.dumps(row.get("prohibited_changed_files", [])), "wall_seconds": row.get("wall_seconds"), "input_tokens": row.get("input_tokens"), "output_tokens": row.get("output_tokens"), "cache_read_tokens": row.get("cache_read_tokens"), "reasoning_tokens": row.get("reasoning_tokens")})
    (root / "task-check-matrix.md").write_text("# Public Characterization V2.3 task matrix\n\nCalibration is excluded from comparison statistics.\n\n" + "\n".join(f"- {row['phase']} / {row['resolved']['provider_model_id']} / {row['task']['family']}: {row['status']}; baseline {''.join('P' if x else 'F' for x in row['baseline_check_vector'])}; final {''.join('P' if x else 'F' for x in row['final_check_vector']) if row.get('final_check_vector') else '—'}; old regressions {row.get('old_contract_regressions', '—')}" for row in allrows) + "\n")
    clean = [row for row in comparative if row["status"] == "completed" and row.get("final_score") is not None]
    configurations = []
    for model, reasoning in COMPARISON_CONFIGURATIONS:
        group = [row for row in comparative if row["resolved"]["provider_model_id"] == model and row["resolved"]["reasoning"] == reasoning]; scored = [row for row in group if row["status"] == "completed" and row.get("final_score") is not None]
        if group: configurations.append({"model": model, "reasoning": reasoning, "attempted": len(group), "completed": len(scored), "completion_rate": len(scored) / len(group), "quality_on_completed": statistics.mean(row["final_score"] for row in scored) if scored else None, "mean_delta": statistics.mean(row["delta_score"] for row in scored) if scored else None, "full_solves": sum(row["full_pass"] is True for row in scored), "old_contract_regressions": sum(row.get("old_contract_regressions", 0) for row in scored), "mean_wall": statistics.mean(row["wall_seconds"] for row in group)})
    (root / "configuration-summary.json").write_text(json.dumps({"calibration_excluded": True, "configurations": configurations}, indent=2, sort_keys=True) + "\n")
    (root / "calibration-summary.json").write_text(json.dumps({"phase": PHASE_CALIBRATION, "attempted": len(calibration), "completed": sum(row["status"] == "completed" for row in calibration), "model": CALIBRATION_CONFIG[0], "reasoning": CALIBRATION_CONFIG[1], "useful": False if not calibration else calibration[0].get("final_score") not in (None, calibration[0].get("baseline_score"), 100.0) and 37.5 <= calibration[0].get("final_score", 0) <= 87.5 and calibration[0].get("old_contract_regressions") == 0}, indent=2, sort_keys=True) + "\n")
    import matplotlib.pyplot as plt
    observations = [row for row in allrows if row.get("status") == "completed" and row.get("final_score") is not None]
    plots = {}
    for filename, xkey, xlabel in (("baseline-vs-final.png", "baseline_score", "baseline new-feature score"), ("final-vs-wall.png", "wall_seconds", "wall seconds"), ("final-vs-tokens.png", "output_tokens", "AGY output tokens")):
        path = root / filename
        if observations:
            plt.figure(figsize=(9, 5)); plt.scatter([row.get(xkey) or 0 for row in observations], [row["final_score"] for row in observations]); plt.xlabel(xlabel); plt.ylabel("final new-feature score"); plt.tight_layout(); plt.savefig(path); plt.close(); plots[filename] = {"status": "created", "observations": len(observations)}
    path = root / "delta-by-configuration.png"
    if observations:
        plt.figure(figsize=(9, 5)); plt.bar([f"{row['resolved']['provider_model_id']} ({row['phase']})" for row in observations], [row["delta_score"] for row in observations]); plt.xticks(rotation=25, ha="right"); plt.ylabel("delta new-feature score"); plt.tight_layout(); plt.savefig(path); plt.close(); plots["delta-by-configuration.png"] = {"status": "created", "observations": len(observations)}
    (root / "plot-metadata.json").write_text(json.dumps(plots, indent=2, sort_keys=True) + "\n")
    (root / "telemetry-semantics.md").write_text("# Telemetry semantics\n\nAGY 1.1.25 request metrics are harness_session, not verified provider requests. Tool event telemetry is unavailable, not observable zero.\n")
    (root / "token-semantics.md").write_text("# Token semantics\n\nInput, output, cache-read, and reasoning values are AGY-reported usage, not verified billing tokens.\n")
    (root / "REPORT.md").write_text(f"# {SUITE_NAME}\n\nClass: {EVALUATION_CLASS}; fixed timeout: {ATTEMPT_TIMEOUT_SECONDS} seconds.\n\nCalibration attempts: {len(calibration)}; comparative attempts: {len(comparative)}; calibration excluded from rankings.\n\nQuality is conditional on clean scored completion. Full pass requires all new checks and zero old-contract regressions.\n")
    (root / "AUDIT_REPORT.md").write_text("# Public Characterization V2.3 audit\n\nV2.3 uses a correct old-contract baseline plus a new cross-cutting feature.\n\n" + ("Calibration was not useful; comparative characterization was not authorized." if not calibration or calibration[0].get("final_score") in (None, calibration[0].get("baseline_score"), 100.0) else "Calibration produced intermediate evidence.") + "\n")
    return {"calibration": calibration, "comparative": configurations}


def _record_suite(conn, instance: TaskInstance, baseline: dict, provenance: dict, reference_at: str):
    suite_id = record_benchmark_suite(conn, SUITE_NAME, EVALUATION_CLASS, SUITE_VERSION, git_sha=provenance["git_sha"], evaluation_class=EVALUATION_CLASS, metadata={"family": instance.family, "calibration_seed": CALIBRATION_SEED, "evaluation_seed": EVALUATION_SEED, "implementation_surface": baseline["implementation_surface"]})
    task_id = record_benchmark_task(conn, suite_id, family=instance.family, task_id=instance.task_id, variant_seed=str(instance.seed), content_hash=sha256_json(instance.files), prompt_hash=baseline["prompt_hash"], evaluator_hash=baseline["visible_verifier_hash"], baseline_score=baseline["baseline_score"], baseline_check_vector=baseline["baseline_check_vector"], task_spec_hash=baseline["task_spec_hash"], allowed_edit_manifest_hash=baseline["allowed_edit_manifest_hash"], reference_validation_passed=True, reference_validation_at=reference_at)
    return suite_id, task_id


def _calibration_useful(rows: list[dict]) -> bool:
    return len(rows) == 1 and rows[0]["status"] == "completed" and rows[0].get("final_score") not in (None, rows[0].get("baseline_score"), 100.0) and 37.5 <= rows[0].get("final_score", 0) <= 87.5 and rows[0].get("old_contract_regressions") == 0 and rows[0].get("full_pass") is not True


def pilot() -> dict:
    gate = validate_preflight(seed=CALIBRATION_SEED, phase=PHASE_CALIBRATION, require_reference=True)
    if not gate["ok"]:
        raise RuntimeError("V2.3 calibration no-inference gates failed; no model started")
    root = state_root()
    if list((root / "calibration-evidence").glob("*.json")) or list((root / "evidence").glob("*.json")):
        raise RuntimeError("V2.3 evidence already exists; retries are prohibited")
    instance = make_instance("P1_snapshot_inventory", CALIBRATION_SEED); baseline = gate["tasks"][0]; provenance = gate["provenance"]; registry = current_registry(); validate_registry(registry); agy = next(item for item in registry if item["name"] == "agy"); conn = connect(); harness_id = record_harness(conn, "agy", version=agy.get("observed_version") or agy["version"], adapter_version="benchmark.public_characterization_v23.runner", transport="agy", capabilities=agy["capabilities"], telemetry=agy["telemetry"], eligibility=agy["eligibility"], evidence_label="public_characterization_non_adversarial", observed_at=now())
    _materialize_public(instance, root); (root / "discovery.json").write_text(json.dumps({"experiment": SUITE_NAME, "evaluation_class": EVALUATION_CLASS, "calibration_seed": CALIBRATION_SEED, "evaluation_seed": EVALUATION_SEED, "calibration_configuration": {"model": CALIBRATION_CONFIG[0], "reasoning": CALIBRATION_CONFIG[1]}, "comparison_configurations": [{"model": model, "reasoning": reasoning} for model, reasoning in COMPARISON_CONFIGURATIONS], "attempt_timeout_seconds": ATTEMPT_TIMEOUT_SECONDS}, indent=2, sort_keys=True) + "\n")
    suite_id, task_id = _record_suite(conn, instance, baseline, provenance, gate["reference_validation"]["validation_timestamp"]); result = _attempt(instance, baseline, CALIBRATION_CONFIG[0], CALIBRATION_CONFIG[1], PHASE_CALIBRATION, root, conn, suite_id, task_id, harness_id, agy.get("observed_version") or agy["version"], agy["telemetry"]); useful = _calibration_useful([result])
    if useful:
        eval_gate = validate_preflight(seed=EVALUATION_SEED, phase=PHASE_COMPARATIVE, require_reference=True)
        if not eval_gate["ok"]:
            raise RuntimeError("V2.3 comparative no-inference gate failed; comparative phase not started")
        eval_instance = make_instance("P1_snapshot_inventory", EVALUATION_SEED); eval_baseline = eval_gate["tasks"][0]; _materialize_public(eval_instance, root); eval_suite, eval_task = _record_suite(conn, eval_instance, eval_baseline, eval_gate["provenance"], eval_gate["reference_validation"]["validation_timestamp"])
        for model, reasoning in COMPARISON_CONFIGURATIONS:
            _attempt(eval_instance, eval_baseline, model, reasoning, PHASE_COMPARATIVE, root, conn, eval_suite, eval_task, harness_id, agy.get("observed_version") or agy["version"], agy["telemetry"])
    summary = {"experiment": SUITE_NAME, "evaluation_class": EVALUATION_CLASS, "suite_git_sha": provenance["git_sha"], "calibration_seed": CALIBRATION_SEED, "evaluation_seed": EVALUATION_SEED, "calibration_attempts": 1, "comparative_attempts": 3 if useful else 0, "calibration_useful": useful, "comparative_ran": useful, "attempts": 1 + (3 if useful else 0), "completed": sum(row["status"] == "completed" for row in _rows(root, PHASE_CALIBRATION) + _rows(root)), "harness_failure": sum(row["status"] == "harness_failure" for row in _rows(root, PHASE_CALIBRATION) + _rows(root)), "explicit_timeout": sum(row["status"] == "explicit_timeout" for row in _rows(root, PHASE_CALIBRATION) + _rows(root)), "evaluator_tampering": sum(row["status"] == "evaluator_tampering" for row in _rows(root, PHASE_CALIBRATION) + _rows(root))}
    (root / "run-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n"); report(root); return summary


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "validate"
    if action == "validate":
        result = validate_preflight(seed=CALIBRATION_SEED, phase=PHASE_CALIBRATION, require_reference="--require-reference" in sys.argv); print(json.dumps(result, indent=2, sort_keys=True)); raise SystemExit(0 if result["ok"] else 1)
    if action == "pilot": print(json.dumps(pilot(), indent=2, sort_keys=True))
    elif action == "report": print(json.dumps(report(), indent=2, sort_keys=True))
    else: raise SystemExit(f"unknown action {action}")
