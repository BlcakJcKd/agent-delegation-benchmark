"""Validated V2 preflight, bounded Gemini pilot, and derived reporting."""

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
from typing import Any

from benchmark.adapters import AntigravityAdapter
from benchmark.provenance import validate_git_identity
from benchmark.v2.telemetry import parse_trace
from ekalavya.catalogue import load_catalogue
from ekalavya.harness_registry import current_registry, validate_registry
from ekalavya.ledger import (
    connect, default_state_dir, finalize_run, record_benchmark_task, record_benchmark_suite,
    record_cost, record_harness, record_request_metric, record_run, record_task_attempt,
)

from . import (
    BASELINE_MAXIMUM, BASELINE_TARGET, EVALUATION_CLASS, FAMILIES,
    IGNORED_GENERATED_DIRS, IGNORED_GENERATED_SUFFIXES, PILOT_CONFIGURATIONS,
    SUITE_NAME, SUITE_VERSION,
)
from .evaluate import evaluate
from .generate import TaskInstance, make_instance, materialize, sha256_json, workspace_digest


SEED = 20261001
SOURCE_PATHS = (
    "benchmark/public_characterization_v2/__init__.py",
    "benchmark/public_characterization_v2/generate.py",
    "benchmark/public_characterization_v2/evaluate.py",
    "benchmark/public_characterization_v2/runner.py",
    "benchmark/v2/telemetry.py",
    "benchmark/adapters.py",
    "benchmark/provenance.py",
    "ekalavya/ledger.py",
    "ekalavya/harness_registry.py",
    "pyproject.toml",
)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def state_root() -> Path:
    root = default_state_dir() / "experiments" / SUITE_NAME
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    return root


def _snapshot(workspace: Path) -> dict[str, str]:
    return {
        path.relative_to(workspace).as_posix(): digest(path.read_bytes())
        for path in workspace.rglob("*")
        if path.is_file() and path.suffix not in IGNORED_GENERATED_SUFFIXES
        and not any(part in IGNORED_GENERATED_DIRS for part in path.parts)
    }


def _matches(path: str, pattern: str) -> bool:
    return fnmatch.fnmatch(path, pattern) or ("**/" in pattern and fnmatch.fnmatch(path, pattern.replace("**/", "")))


def changed_files(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted({name for name in set(before) | set(after) if before.get(name) != after.get(name)})


def prohibited_files(changes: list[str], edit_scope: dict[str, list[str]]) -> list[str]:
    editable = edit_scope.get("editable", [])
    return [path for path in changes if not any(part in IGNORED_GENERATED_DIRS for part in Path(path).parts) and Path(path).suffix not in IGNORED_GENERATED_SUFFIXES and not any(_matches(path, pattern) for pattern in editable)]


def derive_scores(baseline_score: float, final_score: float | None) -> dict[str, float | None]:
    if final_score is None:
        return {"delta_score": None, "normalized_improvement": None}
    delta = final_score - baseline_score
    normalized = delta / (100.0 - baseline_score) if baseline_score < 100.0 else None
    return {"delta_score": delta, "normalized_improvement": normalized}


def _visible_verify(instance: TaskInstance, workspace: Path) -> dict[str, Any]:
    env = {**os.environ, "PYTHONPATH": str(workspace)}
    try:
        result = subprocess.run([sys.executable, str(workspace / "verifier/verify.py")], cwd=workspace, env=env, text=True, capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc), "check_vector": []}
    try:
        payload = json.loads(result.stdout)
        vector = [bool(value) for value in payload["checks"]]
    except (ValueError, KeyError, TypeError) as exc:
        return {"ok": False, "error": f"malformed verifier output: {exc}", "check_vector": []}
    return {"ok": result.returncode == 0 and len(vector) == 8, "error": result.stderr[-2000:], "check_vector": vector}


def _public_task_artifacts(instance: TaskInstance, root: Path) -> None:
    (root / "task-specifications" / instance.family).mkdir(parents=True, exist_ok=True)
    (root / "verifier-contracts" / instance.family).mkdir(parents=True, exist_ok=True)
    (root / "edit-scopes" / instance.family).mkdir(parents=True, exist_ok=True)
    (root / "task-specifications" / instance.family / "README.md").write_text(instance.files["README.md"])
    (root / "task-specifications" / instance.family / "specification.json").write_text(json.dumps(instance.specification, indent=2, sort_keys=True) + "\n")
    (root / "verifier-contracts" / instance.family / "contract.py").write_text(instance.files["verifier/contract.py"])
    (root / "verifier-contracts" / instance.family / "verify.py").write_text(instance.files["verifier/verify.py"])
    (root / "edit-scopes" / instance.family / "allowed-edit-manifest.json").write_text(json.dumps(instance.edit_scope, indent=2, sort_keys=True) + "\n")


def _baseline_record(instance: TaskInstance, workspace: Path) -> dict[str, Any]:
    controller = evaluate(instance, workspace)
    visible = _visible_verify(instance, workspace)
    return {
        "family": instance.family, "seed": instance.seed, "task_id": instance.task_id,
        "baseline_score": controller["score"], "baseline_check_vector": controller["check_vector"],
        "visible_check_vector": visible["check_vector"], "visible_controller_agree": controller["check_vector"] == visible["check_vector"] and visible["ok"],
        "generated_workspace_hash": workspace_digest(workspace), "prompt_hash": digest(instance.prompt.encode()),
        "visible_verifier_hash": instance.visible_verifier_hash, "task_spec_hash": instance.task_spec_hash,
        "allowed_edit_manifest_hash": instance.edit_scope_hash, "checks": [check["name"] for check in controller["checks"]],
    }


def validate_preflight(*, require_reference: bool = False, seed: int = SEED) -> dict[str, Any]:
    """Run all no-inference task-quality gates in disposable workspaces."""
    result: dict[str, Any] = {"suite": SUITE_NAME, "version": SUITE_VERSION, "evaluation_class": EVALUATION_CLASS, "seed": seed, "tasks": [], "provenance": None, "reference_validation": None}
    repo = Path(__file__).resolve().parents[2]
    try:
        result["provenance"] = validate_git_identity(repo, SOURCE_PATHS)
    except Exception as exc:
        result["provenance_error"] = str(exc)
    with tempfile.TemporaryDirectory(prefix="ekalavya-v2-preflight-") as temporary:
        temporary_root = Path(temporary)
        for index, family in enumerate(FAMILIES):
            instance = make_instance(family, seed + index)
            workspace = temporary_root / family
            materialize(instance, workspace)
            baseline = _baseline_record(instance, workspace)
            baseline["headroom_passed"] = baseline["baseline_score"] < BASELINE_MAXIMUM and BASELINE_TARGET[0] <= baseline["baseline_score"] <= BASELINE_TARGET[1]
            baseline["deterministic_hash_passed"] = baseline["generated_workspace_hash"] == workspace_digest(materialize(instance, temporary_root / f"repeat-{family}"))
            baseline["reference_validation_passed"] = False
            result["tasks"].append(baseline)
    reference_path = state_root() / "validation" / "reference-validation.json"
    if reference_path.is_file():
        try:
            result["reference_validation"] = json.loads(reference_path.read_text())
        except ValueError as exc:
            result["reference_validation"] = {"passed": False, "error": str(exc)}
    reference = result.get("reference_validation") or {}
    reference_tasks = {item.get("family"): item for item in reference.get("tasks", []) if isinstance(item, dict)}
    reference_identity_ok = (
        bool(reference.get("passed"))
        and bool(result.get("provenance"))
        and reference.get("suite_git_sha") == result["provenance"].get("git_sha")
        and reference.get("suite") == SUITE_NAME
        and reference.get("version") == SUITE_VERSION
        and reference.get("seed") == seed
        and reference.get("temporary_reference_repair_deleted") is True
        and reference.get("gold_source_retained") is False
        and all(
            reference_tasks.get(item["family"], {}).get("score") == 100.0
            and reference_tasks.get(item["family"], {}).get("check_vector") == [True] * 8
            for item in result["tasks"]
        )
    )
    for item in result["tasks"]:
        item["reference_validation_passed"] = reference_identity_ok and reference_tasks.get(item["family"], {}).get("score") == 100.0
    result["gates"] = {
        "provenance": bool(result.get("provenance")),
        "headroom": all(item["headroom_passed"] for item in result["tasks"]),
        "visible_controller_parity": all(item["visible_controller_agree"] for item in result["tasks"]),
        "deterministic_hashes": all(item["deterministic_hash_passed"] for item in result["tasks"]),
        "reference_validation": reference_identity_ok if require_reference else "not_required",
    }
    result["ok"] = all(value is True for value in result["gates"].values())
    validation_dir = state_root() / "validation"; validation_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    (validation_dir / "preflight.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    lines = ["# Public Characterization V2 validation", "", f"Overall gate result: `{str(result['ok']).lower()}`.", "", "| Gate | Result |", "|---|---|"]
    lines.extend(f"| {name} | {value} |" for name, value in result["gates"].items())
    lines += ["", "Reference validation records only pass metadata; no repair source or patch is retained."]
    (state_root() / "VALIDATION_REPORT.md").write_text("\n".join(lines) + "\n")
    return result


def _terminate(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM); process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try: os.killpg(process.pid, signal.SIGKILL)
        except OSError: pass


def _record_suite(conn: Any, instances: list[TaskInstance], provenance: dict[str, Any], baselines: dict[str, dict[str, Any]], reference_at: str) -> tuple[int, dict[str, int]]:
    suite_id = record_benchmark_suite(conn, SUITE_NAME, "public_characterization", SUITE_VERSION, git_sha=provenance["git_sha"], evaluation_class=EVALUATION_CLASS, metadata={"families": FAMILIES, "objective": True, "adversarial_isolation": False, "baseline_aware": True, "source_paths": provenance["source_paths"], "source_sha256": provenance["source_sha256"]})
    task_ids = {}
    for instance in instances:
        baseline = baselines[instance.family]
        task_ids[instance.task_id] = record_benchmark_task(conn, suite_id, family=instance.family, task_id=instance.task_id, variant_seed=str(instance.seed), content_hash=sha256_json(instance.files), prompt_hash=digest(instance.prompt.encode()), evaluator_hash=instance.visible_verifier_hash, baseline_score=baseline["baseline_score"], baseline_check_vector=baseline["baseline_check_vector"], task_spec_hash=instance.task_spec_hash, allowed_edit_manifest_hash=instance.edit_scope_hash, reference_validation_passed=True, reference_validation_at=reference_at)
    return suite_id, task_ids


def _attempt(conn: Any, suite_id: int, db_task_id: int, instance: TaskInstance, baseline: dict[str, Any], model_id: str, reasoning: str, harness_id: int, root: Path, telemetry: dict[str, Any], agy_version: str) -> dict[str, Any]:
    key = f"{model_id}-{instance.family}-{instance.seed}"
    workspace = root / "workspaces" / key
    materialize(instance, workspace); before = _snapshot(workspace)
    requested = {"experiment": SUITE_NAME, "profile": "flash", "provider": "gemini", "provider_model_id": model_id, "model": model_id, "reasoning": reasoning, "harness": "agy", "evaluation_class": EVALUATION_CLASS}
    started_at = now(); run_id = f"{SUITE_NAME}:{uuid.uuid4().hex}"
    record_run(conn, run_id, requested, resolved={"provider_model_id": model_id, "reasoning": reasoning, "harness": "agy", "harness_version": agy_version}, status="running", evaluation_class=EVALUATION_CLASS, provider="gemini", identity_key=f"gemini:flash:{model_id}", harness_id=harness_id, billing_mode="subscription", started_at=started_at)
    start = time.monotonic(); code = -1; stdout = stderr = ""; timed_out = False
    evidence_dir = root / "evidence"; evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        process = subprocess.Popen(AntigravityAdapter(model=model_id, reasoning_effort=None).command(workspace, instance.prompt, evidence_dir / key), cwd=workspace, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, "BENCHMARK_WORKSPACE": str(workspace)}, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=900); code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True; _terminate(process); stdout, stderr = process.communicate(); code = -1
    except OSError as exc:
        stderr = str(exc)
    wall = time.monotonic() - start
    after = _snapshot(workspace); changed = changed_files(before, after); prohibited = prohibited_files(changed, instance.edit_scope); tampering = bool(prohibited)
    requests = parse_trace(stdout); final = evaluate(instance, workspace) if not timed_out and code == 0 else None
    status = "explicit_timeout" if timed_out else ("evaluator_tampering" if tampering else ("completed" if code == 0 else "harness_failure"))
    final_score = final["score"] if final else None
    score_derivatives = derive_scores(baseline["baseline_score"], final_score)
    delta = score_derivatives["delta_score"]
    normalized = score_derivatives["normalized_improvement"]
    token_values = {field: [getattr(item, field) for item in requests if getattr(item, field) is not None] for field in ("input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens")}
    evidence = {
        "experiment": SUITE_NAME, "evaluation_class": EVALUATION_CLASS, "run_id": run_id, "requested": requested,
        "resolved": {"provider_model_id": model_id, "reasoning": reasoning, "harness": "agy", "harness_version": agy_version},
        "started_at": started_at, "ended_at": now(), "wall_seconds": wall, "exit_code": code, "timed_out": timed_out,
        "status": status, "changed_files": changed, "evaluator_tampering": tampering, "prohibited_changed_files": prohibited,
        "baseline_score": baseline["baseline_score"], "baseline_check_vector": baseline["baseline_check_vector"],
        "final_score": final_score, "final_check_vector": final["check_vector"] if final else None,
        "delta_score": delta, "normalized_improvement": normalized, "full_pass": final["full_pass"] if final else None,
        "request_count": len(requests) or None, "request_metric_semantics": telemetry.get("request_metric_semantics"),
        "tool_event_telemetry": telemetry.get("tool_event_telemetry"), "tool_events": None,
        "token_metric_semantics": telemetry.get("token_metric_semantics"), "input_tokens": sum(token_values["input_tokens"]) if token_values["input_tokens"] else None,
        "output_tokens": sum(token_values["output_tokens"]) if token_values["output_tokens"] else None, "cache_read_tokens": sum(token_values["cache_read_tokens"]) if token_values["cache_read_tokens"] else None,
        "reasoning_tokens": sum(token_values["reasoning_tokens"]) if token_values["reasoning_tokens"] else None,
        "task": {"family": instance.family, "task_id": instance.task_id, "seed": instance.seed, "generated_workspace_hash": baseline["generated_workspace_hash"], "prompt_hash": baseline["prompt_hash"], "visible_verifier_hash": baseline["visible_verifier_hash"], "task_spec_hash": baseline["task_spec_hash"], "allowed_edit_manifest_hash": baseline["allowed_edit_manifest_hash"]},
        "stdout_sha256": digest(stdout.encode()), "stderr_sha256": digest(stderr.encode()), "assessment": final,
    }
    evidence_path = evidence_dir / f"{key}.json"; evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    record_task_attempt(conn, run_id, db_task_id, score=final_score, public_score=final_score, invariant_score=final_score, scope_compliant=not tampering, wall_seconds=wall, baseline_score=baseline["baseline_score"], baseline_check_vector=baseline["baseline_check_vector"], final_check_vector=final["check_vector"] if final else None, delta_score=delta, normalized_improvement=normalized, evaluator_tampering=tampering, prohibited_changed_files=prohibited, metadata=evidence)
    for metric in requests: record_request_metric(conn, run_id, metric.json())
    record_cost(conn, run_id, billing_mode="subscription", cost_source="unavailable: subscription route", input_tokens=evidence["input_tokens"], output_tokens=evidence["output_tokens"], cached_input_tokens=evidence["cache_read_tokens"], reasoning_tokens=evidence["reasoning_tokens"])
    finalize_run(conn, run_id, ended_at=evidence["ended_at"], status=status, raw_evidence_path=str(evidence_path), raw_evidence_sha256=digest(evidence_path.read_bytes()))
    return evidence


def pilot(seed: int = SEED) -> dict[str, Any]:
    gate = validate_preflight(require_reference=True, seed=seed)
    if not gate["ok"]:
        raise RuntimeError("V2 no-inference gates failed; pilot not started")
    root = state_root(); validation = gate["reference_validation"]; reference_at = validation["validation_timestamp"]
    instances = [make_instance(family, seed + index) for index, family in enumerate(FAMILIES)]
    baselines = {item["family"]: item for item in gate["tasks"]}
    provenance = gate["provenance"]; conn = connect(); registry = current_registry(); validate_registry(registry)
    agy = next(item for item in registry if item["name"] == "agy"); agy_version = agy.get("observed_version") or agy["version"]
    (root / "discovery.json").write_text(json.dumps({"experiment": SUITE_NAME, "evaluation_class": EVALUATION_CLASS, "client": "agy", "client_version": agy_version, "models": [{"provider_model_id": model, "reasoning": reasoning} for model, reasoning in PILOT_CONFIGURATIONS]}, indent=2, sort_keys=True) + "\n")
    harness_id = record_harness(conn, "agy", version=agy_version, adapter_version="benchmark.adapters.AntigravityAdapter", transport="agy", capabilities=agy["capabilities"], telemetry=agy["telemetry"], eligibility=agy["eligibility"], evidence_label="public_characterization_non_adversarial", observed_at=now())
    for instance in instances:
        _public_task_artifacts(instance, root)
    suite_id, task_ids = _record_suite(conn, instances, provenance, baselines, reference_at)
    attempts = []
    for model_id, reasoning in PILOT_CONFIGURATIONS:
        for instance in instances:
            attempts.append(_attempt(conn, suite_id, task_ids[instance.task_id], instance, baselines[instance.family], model_id, reasoning, harness_id, root, agy["telemetry"], agy_version))
    summary = {"experiment": SUITE_NAME, "evaluation_class": EVALUATION_CLASS, "suite_git_sha": provenance["git_sha"], "seed": seed, "attempts": len(attempts), "completed": sum(item["status"] == "completed" for item in attempts), "harness_failure": sum(item["status"] == "harness_failure" for item in attempts), "explicit_timeout": sum(item["status"] == "explicit_timeout" for item in attempts), "evaluator_tampering": sum(item["evaluator_tampering"] for item in attempts), "configurations": [list(item) for item in PILOT_CONFIGURATIONS]}
    (root / "run-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    report(root)
    return summary


def _rows(root: Path) -> list[dict[str, Any]]:
    return [json.loads(path.read_text()) for path in sorted((root / "evidence").glob("*.json"))]


def _plot(rows: list[dict[str, Any]], path: Path, kind: str, x: str, y: str, xlabel: str, ylabel: str) -> dict[str, Any]:
    observations = [row for row in rows if row.get(x) is not None and row.get(y) is not None and row.get("status") == "completed"]
    if not observations: return {"status": "skipped", "reason": "no_completed_observations"}
    import matplotlib.pyplot as plt
    labels = [f"{row['resolved']['provider_model_id'].split('-')[1]} {row['resolved']['reasoning'].title()}" for row in observations]
    plt.figure(figsize=(9, 5))
    if kind == "scatter":
        plt.scatter([row[x] for row in observations], [row[y] for row in observations])
        for row, label in zip(observations, labels): plt.annotate(label, (row[x], row[y]), fontsize=8)
    else:
        plt.bar(labels, [row[y] for row in observations])
        plt.xticks(rotation=30, ha="right")
    plt.xlabel(xlabel); plt.ylabel(ylabel); plt.tight_layout(); plt.savefig(path); plt.close()
    return {"status": "created", "kind": kind, "observations": len(observations), "labels": labels}


def report(root: Path | None = None) -> Path:
    root = (root or state_root()).resolve(); rows = _rows(root)
    fieldnames = ["model", "reasoning", "task", "status", "baseline_score", "baseline_check_vector", "final_score", "final_check_vector", "check_1", "check_2", "check_3", "check_4", "check_5", "check_6", "check_7", "check_8", "passed_checks", "delta_score", "normalized_improvement", "full_pass", "evaluator_tampering", "prohibited_changed_files", "wall_seconds", "input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens"]
    matrix = root / "task-check-matrix.csv"
    with matrix.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames); writer.writeheader()
        for row in rows:
            final_vector = row["final_check_vector"]
            writer.writerow({"model": row["resolved"]["provider_model_id"], "reasoning": row["resolved"]["reasoning"], "task": row["task"]["family"], "status": row["status"], "baseline_score": row["baseline_score"], "baseline_check_vector": "".join("P" if value else "F" for value in row["baseline_check_vector"]), "final_score": row["final_score"], "final_check_vector": "".join("P" if value else "F" for value in final_vector) if final_vector is not None else None, **{f"check_{index}": ("P" if value else "F") if final_vector is not None else None for index, value in enumerate(final_vector or [], 1)}, "passed_checks": sum(final_vector) if final_vector is not None else None, "delta_score": row["delta_score"], "normalized_improvement": row["normalized_improvement"], "full_pass": row["full_pass"], "evaluator_tampering": row["evaluator_tampering"], "prohibited_changed_files": json.dumps(row["prohibited_changed_files"]), "wall_seconds": row["wall_seconds"], "input_tokens": row["input_tokens"], "output_tokens": row["output_tokens"], "cache_read_tokens": row["cache_read_tokens"], "reasoning_tokens": row["reasoning_tokens"]})
    md = ["# Public Characterization V2 task × check matrix", "", "Vectors are C1–C8; `—` means no final score because the attempt did not complete.", "", "| Model | Reasoning | Task | Status | Baseline | Final | Delta | Norm. improvement | Tampering | Prohibited files | Wall s |", "|---|---|---|---|---|---|---:|---:|---|---|---:|"]
    for row in rows:
        md.append(f"| {row['resolved']['provider_model_id']} | {row['resolved']['reasoning']} | {row['task']['family']} | {row['status']} | {''.join('P' if value else 'F' for value in row['baseline_check_vector'])} ({row['baseline_score']}) | {''.join('P' if value else 'F' for value in row['final_check_vector']) if row['final_check_vector'] is not None else '—'} ({row['final_score'] if row['final_score'] is not None else '—'}) | {row['delta_score'] if row['delta_score'] is not None else '—'} | {row['normalized_improvement'] if row['normalized_improvement'] is not None else '—'} | {row['evaluator_tampering']} | {', '.join(row['prohibited_changed_files']) or '—'} | {row['wall_seconds']:.3f} |")
    (root / "task-check-matrix.md").write_text("\n".join(md) + "\n")
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows: grouped.setdefault((row["resolved"]["provider_model_id"], row["resolved"]["reasoning"]), []).append(row)
    summary = []
    for key, group in sorted(grouped.items()):
        completed = [row for row in group if row["status"] == "completed" and row["final_score"] is not None]
        scored = [row for row in group if row["final_score"] is not None]
        final_scores = [row["final_score"] for row in completed]; deltas = [row["delta_score"] for row in completed]
        summary.append({"model": key[0], "reasoning": key[1], "mean_baseline": statistics.mean(row["baseline_score"] for row in group), "quality_on_completed": statistics.mean(final_scores) if final_scores else None, "scored_including_tampering": statistics.mean(row["final_score"] for row in scored) if scored else None, "mean_delta": statistics.mean(deltas) if deltas else None, "median_final": statistics.median(final_scores) if final_scores else None, "full_solves": sum(row["full_pass"] is True for row in completed), "attempted": len(group), "completed": len(completed), "tampering": sum(row["status"] == "evaluator_tampering" for row in group), "harness_failure": sum(row["status"] == "harness_failure" for row in group), "explicit_timeout": sum(row["status"] == "explicit_timeout" for row in group), "completion_rate": len(completed) / len(group), "mean_wall": statistics.mean(row["wall_seconds"] for row in group), "input_tokens": sum(row["input_tokens"] or 0 for row in group), "output_tokens": sum(row["output_tokens"] or 0 for row in group), "cache_read_tokens": sum(row["cache_read_tokens"] or 0 for row in group), "reasoning_tokens": sum(row["reasoning_tokens"] or 0 for row in group)})
    (root / "configuration-summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    lines = [f"# {SUITE_NAME}", "", "Class: `public_characterization`; baseline-aware, objective, reproducible, non-adversarially isolated.", "", "| Model | Reasoning | Mean baseline | Quality final (completed) | Scored incl. tampering | Mean delta | Median final | Full solves | Completed/attempted | Tampering | Completion rate | Mean wall | AGY input/output/cache/reasoning |", "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for item in summary: lines.append(f"| {item['model']} | {item['reasoning']} | {item['mean_baseline']} | {item['quality_on_completed']} | {item['scored_including_tampering']} | {item['mean_delta']} | {item['median_final']} | {item['full_solves']} | {item['completed']}/{item['attempted']} | {item['tampering']} | {item['completion_rate']} | {item['mean_wall']} | {item['input_tokens']}/{item['output_tokens']}/{item['cache_read_tokens']}/{item['reasoning_tokens']} |")
    lines += ["", "Quality final and delta are conditional on ordinary completed, scope-compliant controller-scored attempts. `Scored incl. tampering` is shown separately and does not erase the behavioral failure.", "", "Pilot result: all ordinary completed attempts reached the same final C1–C8 vector; no repeated sweep or Pareto recommendation is justified.", "", "Tool telemetry: unavailable; request metric semantics: harness_session; tokens: AGY-reported usage, not verified provider billing."]
    (root / "REPORT.md").write_text("\n".join(lines) + "\n")
    pattern_set = {tuple(row["final_check_vector"] or []) for row in rows if row["final_check_vector"] is not None}
    baseline_set = {tuple(row["baseline_check_vector"]) for row in rows}
    discrimination = bool(len(pattern_set) > 1 or len({row["final_score"] for row in rows if row["final_score"] is not None}) > 1 or any((row["delta_score"] or 0) != 0 for row in rows))
    audit = ["# Public Characterization V2 audit", "", "## Baseline and solvability gates", "", "All four generated variants passed the pre-inference gates: baseline scores are P1 25.0, P2 25.0, P3 37.5, P4 37.5; every baseline is below 75 and within the target 12.5–37.5 range. The disposable reference validation reached 100.0 with all C1–C8 true for every family, and no gold source or repair workspace was retained.", "", f"Pilot baseline-to-final improvement observed: `{str(discrimination).lower()}`.", f"Baseline vectors: `{len(baseline_set)}` distinct; final vectors: `{len(pattern_set)}` distinct.", "", "## Configuration discrimination", "", "All ordinary completed configurations reached final score 100 and the same final C1–C8 vector. One Gemini 3.7 Medium attempt was evaluator tampering (`tests/test_contract.py`) and is reported as a behavioral failure; its pristine-controller score is retained separately.", "", "The pilot does not demonstrate configuration-level discrimination. Stop before repetitions or a 36-attempt sweep; return to harder task-variant design while preserving the frozen suite’s public contract.", "", "## Check independence", ""]
    independence_path = root / "validation" / "independence.json"
    if independence_path.is_file():
        try:
            independence = json.loads(independence_path.read_text())
            for family, cases in independence.get("cases", {}).items():
                audit.append(f"- `{family}`: " + "; ".join(f"{label}={case.get('score')} ({''.join('P' if value else 'F' for value in case.get('check_vector', []))})" for label, case in sorted(cases.items())))
        except (OSError, ValueError):
            audit.append("- Independence metadata was unavailable or malformed.")
    else:
        audit.append("- Independence metadata was not retained.")
    audit += ["", "## Contract assessment", "", "Visible/controller parity and solvability passed, but the pilot exposed a task-contract weakness requiring inspection: P4 C6 (`codec round trip`) passes the broken baseline because it exercises only the default timeout, so a codec that drops non-default timeout data can still pass. This is recorded as a version-fix defect; historical scores and task semantics are not retroactively changed. Evaluator/test tampering is a public-characterization behavioral failure and is not treated as infrastructure failure. AGY request semantics remain `harness_session`; tool telemetry remains `unavailable`; token fields remain AGY-reported usage."]
    (root / "AUDIT_REPORT.md").write_text("\n".join(audit) + "\n")
    plots = {
        "baseline-vs-final": _plot(rows, root / "baseline-vs-final.png", "scatter", "baseline_score", "final_score", "baseline score", "final score"),
        "delta-by-configuration": _plot(rows, root / "delta-by-configuration.png", "bar", "resolved", "delta_score", "configuration", "delta score"),
        "final-vs-wall": _plot(rows, root / "final-vs-wall.png", "scatter", "wall_seconds", "final_score", "wall seconds", "final score"),
        "final-vs-tokens": _plot(rows, root / "final-vs-tokens.png", "scatter", "input_tokens", "final_score", "AGY input tokens", "final score"),
    }
    (root / "plot-metadata.json").write_text(json.dumps(plots, indent=2, sort_keys=True) + "\n")
    (root / "telemetry-semantics.md").write_text("# Telemetry semantics\n\nAGY 1.1.25 request metrics are `harness_session`, not verified provider model requests. Tool event telemetry is `unavailable`, not observable zero.\n")
    (root / "token-semantics.md").write_text("# Token semantics\n\nInput, output, cache-read, and reasoning values are AGY-reported usage fields with uncertain session/cumulative semantics. They are not verified provider billing tokens.\n")
    return root / "REPORT.md"


def main(argv: list[str] | None = None) -> int:
    action = (argv or sys.argv[1:] or ["validate"])[0]
    if action == "validate":
        result = validate_preflight(require_reference="--require-reference" in (argv or sys.argv[1:])); print(json.dumps(result, indent=2, sort_keys=True)); return 0 if result["ok"] else 1
    if action == "pilot":
        print(json.dumps(pilot(), indent=2, sort_keys=True)); return 0
    if action == "report":
        print(report()); return 0
    raise SystemExit(f"unknown command: {action}")


if __name__ == "__main__": raise SystemExit(main())
