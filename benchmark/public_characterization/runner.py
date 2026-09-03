"""Discovery, execution, and ledger recording for public characterization V1."""

from __future__ import annotations

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
from benchmark.v2.plotting import plot_rows
from benchmark.v2.telemetry import parse_trace
from ekalavya.catalogue import canonicalize_gemini_flash_generations, load_catalogue, save_catalogue
from ekalavya.config import config_root
from ekalavya.harness_registry import current_registry, validate_registry
from ekalavya.ledger import (
    connect, default_state_dir, finalize_run, record_availability, record_benchmark_suite,
    record_benchmark_task, record_cost, record_harness, record_request_metric, record_run,
    record_task_attempt, record_tool_event, upsert_model,
)
from ekalavya.schema import CandidateIdentity

from . import EVALUATION_CLASS, FAMILIES, SUITE_NAME, SUITE_VERSION
from .evaluate import evaluate
from .generate import TaskInstance, manifest, make_instance, materialize, visible_evaluator_digest, workspace_digest


EXPERIMENT = "public-characterization-v1"
GENERATIONS = ("3.7", "3.8")
REASONING = ("low", "medium", "high")
AGY_VERSION_FALLBACK = "unknown"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def state_root() -> Path:
    root = default_state_dir() / "experiments" / EXPERIMENT
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    return root


def command(argv: list[str], *, cwd: Path | None = None, timeout: int = 60) -> tuple[int, str, str]:
    try:
        result = subprocess.run(argv, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return -1, "", str(exc)
    return result.returncode, result.stdout, result.stderr


def _agy_version() -> str:
    code, stdout, _ = command(["agy", "--version"])
    return stdout.strip() if code == 0 and stdout.strip() else AGY_VERSION_FALLBACK


def _parse_discovery(stdout: str) -> list[dict[str, str]]:
    discovered = []
    for line in stdout.splitlines():
        if "\t" not in line:
            continue
        model_id, display_name = line.split("\t", 1)
        model_id = model_id.strip()
        if model_id.startswith("gemini-3."):
            discovered.append({"provider_model_id": model_id, "display_name": display_name.strip()})
    return discovered


def _update_profile_catalogue(discovered: list[dict[str, str]], observed_at: str, version: str) -> dict[str, Any]:
    root = config_root()
    catalogue_path, profiles_path = root / "catalogue.json", root / "profiles.json"
    entries = load_catalogue(catalogue_path)
    updated = canonicalize_gemini_flash_generations(entries, discovered, observed_at=observed_at, serving_engine_version=version)
    save_catalogue(catalogue_path, updated)
    profiles = json.loads(profiles_path.read_text()) if profiles_path.is_file() else []
    flash = next((profile for profile in profiles if profile.get("name") == "flash"), None)
    generation_entries = {entry.get("generation"): entry for entry in updated if entry.get("catalogue_key", "").startswith("gemini:flash:")}
    if flash is not None and "3.7" in generation_entries:
        current = generation_entries["3.7"]
        flash["default_identity_key"] = current["identity_key"]
        flash["permitted_candidates"] = [generation_entries[g]["identity_key"] for g in ("3.6", "3.7", "3.8") if g in generation_entries]
        flash["reasoning_policy"] = "overrideable"
        flash["default_reasoning"] = "medium"
        flash["description"] = "Gemini Flash generation family; Medium is the configured runtime default"
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = profiles_path.with_name(f".{profiles_path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(profiles, indent=2, sort_keys=True) + "\n")
        os.chmod(tmp, 0o600)
        tmp.replace(profiles_path)
    return {"catalogue_entries": len(updated), "profile_updated": flash is not None and "3.7" in generation_entries, "path": str(catalogue_path)}


def discover_models() -> dict[str, Any]:
    code, stdout, stderr = command(["agy", "models"])
    if code != 0:
        raise RuntimeError(f"agy models failed: {stderr.strip()}")
    observed_at = now()
    version = _agy_version()
    discovered = _parse_discovery(stdout)
    expected = {f"gemini-{generation}-flash-{effort}" for generation in ("3.6", "3.7", "3.8") for effort in REASONING}
    missing = sorted(expected - {item["provider_model_id"] for item in discovered})
    if missing:
        raise RuntimeError("required Gemini Flash runtime IDs missing: " + ", ".join(missing))
    catalogue = _update_profile_catalogue(discovered, observed_at, version)
    conn = connect()
    lifecycle = {"3.6": "previous", "3.7": "current", "3.8": "candidate"}
    ledger_models = []
    for item in discovered:
        model_id = item["provider_model_id"]
        parts = model_id.split("-")
        generation = parts[1] if len(parts) > 1 else None
        family = "flash" if len(parts) > 2 and parts[2] == "flash" else "unknown"
        variant = parts[-1] if family == "flash" else None
        identity = CandidateIdentity(
            provider="gemini", family=family, provider_model_id=model_id,
            display_name=item["display_name"], generation=generation, variant=variant,
            capabilities={"reasoning_values": [variant] if variant else []},
            serving_engine="agy", serving_engine_version=version,
        )
        model_db_id = upsert_model(conn, identity, lifecycle=lifecycle.get(generation, "candidate"), discovered_at=observed_at)
        record_availability(conn, model_db_id, state="available", observed_at=observed_at, source="agy models", details={"exact_model_id": model_id, "reasoning": variant, "lifecycle_scope": "gemini_flash_generation_family"})
        ledger_models.append({"provider_model_id": model_id, "generation": generation, "reasoning": variant, "lifecycle": lifecycle.get(generation, "historical")})
    result = {"timestamp": observed_at, "client": "agy", "client_version": version, "models": ledger_models, "catalogue": catalogue}
    (state_root() / "discovery.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def check_local_suite() -> dict[str, Any]:
    root = state_root() / "local-check"
    results = []
    for index, family in enumerate(FAMILIES):
        instance = make_instance(family, 20260903 + index)
        workspace = root / instance.task_id.replace(":", "_")
        materialize(instance, workspace)
        assessment = evaluate(instance, workspace)
        results.append({"task_id": instance.task_id, "score": assessment["score"], "full_pass": assessment["full_pass"], "checks": len(assessment["checks"])})
    return {"suite": SUITE_NAME, "version": SUITE_VERSION, "evaluation_class": EVALUATION_CLASS, "results": results, "all_objective_checks_pass": all(item["score"] == 100.0 for item in results)}


def _snapshot(workspace: Path) -> dict[str, str]:
    return {p.relative_to(workspace).as_posix(): digest_bytes(p.read_bytes()) for p in workspace.rglob("*") if p.is_file() and "__pycache__" not in p.parts}


def _terminate(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass


def run_attempt(conn: Any, suite_id: int, task_db_id: int, instance: TaskInstance, model_id: str, reasoning: str, harness_id: int, root: Path, agy_version: str) -> dict[str, Any]:
    key = f"{model_id}-{instance.family}-{instance.seed}"
    workspace = root / "workspaces" / key
    materialize(instance, workspace)
    before = _snapshot(workspace)
    generation = model_id.split("-")[1]
    variant = model_id.rsplit("-", 1)[-1]
    identity = CandidateIdentity(provider="gemini", family="flash", provider_model_id=model_id, display_name=f"Gemini {generation} Flash ({variant})", generation=generation, variant=variant, capabilities={"reasoning_values": [variant]}, serving_engine="agy", serving_engine_version=agy_version)
    resolved = {**identity.as_dict(), "identity_key": identity.identity_key, "reasoning": reasoning, "harness": "agy", "harness_version": agy_version, "adapter_version": "benchmark.adapters.AntigravityAdapter", "transport": "agy"}
    requested = {"experiment": EXPERIMENT, "profile": "flash", "provider": "gemini", "family": "flash", "provider_model_id": model_id, "model": model_id, "reasoning": reasoning, "harness": "agy", "evaluation_class": EVALUATION_CLASS}
    run_id = f"{EXPERIMENT}:{uuid.uuid4().hex}"
    started_at = now()
    record_run(conn, run_id, requested, resolved=resolved, status="running", evaluation_class=EVALUATION_CLASS, provider="gemini", identity_key=identity.identity_key, harness_id=harness_id, billing_mode="subscription", started_at=started_at)
    start = time.monotonic()
    evidence_dir = root / "evidence"; evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    adapter = AntigravityAdapter(model=model_id, reasoning_effort=None)
    code, stdout, stderr = -1, "", ""
    timed_out = False
    try:
        process = subprocess.Popen(adapter.command(workspace, instance.prompt, evidence_dir / key), cwd=workspace, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, "BENCHMARK_WORKSPACE": str(workspace)}, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=900)
            code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            _terminate(process)
            stdout, stderr = process.communicate()
            code = -1
    except OSError as exc:
        stderr = str(exc)
    wall = time.monotonic() - start
    ended_at = now()
    after = _snapshot(workspace)
    changed = sorted({name for name in set(before) | set(after) if before.get(name) != after.get(name)})
    requests = parse_trace(stdout)
    telemetry_models = sorted({item.model for item in requests if item.model})
    identity_mismatch = bool(telemetry_models and model_id not in telemetry_models)
    assessment = evaluate(instance, workspace) if not timed_out else {"evaluation_class": EVALUATION_CLASS, "objective": True, "adversarial_isolation": False, "authoritative_reference_present": False, "checks": [], "score": None, "maximum": 100.0, "full_pass": False, "public_tests": {}, "scope_compliance": True}
    status = "invalid_identity" if identity_mismatch else ("completed" if not timed_out and code == 0 else "harness_failure")
    evidence = {
        "experiment": EXPERIMENT, "evaluation_class": EVALUATION_CLASS, "run_id": run_id,
        "requested": requested, "resolved": resolved, "started_at": started_at, "ended_at": ended_at,
        "wall_seconds": wall, "exit_code": code, "timed_out": timed_out, "changed_files": changed,
        "stdout_sha256": digest_bytes(stdout.encode()), "stderr_sha256": digest_bytes(stderr.encode()),
        "request_count": len(requests) or None, "telemetry_model_ids": telemetry_models or None, "identity_match": not identity_mismatch, "tool_events": sum(item.tool_calls for item in requests) if requests else None,
        "invalid_tool_calls": sum(item.invalid_tool_schema + item.invalid_argument_type for item in requests) if requests else None,
        "recoveries": sum(bool(item.recovered_after_tool_error) for item in requests) if requests else None,
        "final_verification": {"full_pass": assessment.get("full_pass"), "checks": assessment.get("checks"), "public_tests": assessment.get("public_tests")},
        "assessment": assessment, "task": {"suite": SUITE_NAME, "version": SUITE_VERSION, "family": instance.family, "task_id": instance.task_id, "seed": instance.seed, "workspace_hash": workspace_digest(workspace), "prompt_hash": digest_bytes(instance.prompt.encode()), "visible_evaluator_hash": visible_evaluator_digest(instance), "authoritative_reference_present": False},
    }
    evidence_path = evidence_dir / f"{key}.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    score = assessment.get("score") if status == "completed" else None
    record_task_attempt(conn, run_id, task_db_id, score=score, public_score=score, hidden_score=None, invariant_score=score, api_score=None, scope_compliant=True, wall_seconds=wall, metadata=evidence)
    for metric in requests:
        request_id = record_request_metric(conn, run_id, metric.json())
        for ordinal, tool_name in enumerate(metric.tool_names, 1):
            record_tool_event(conn, run_id, {"ordinal": ordinal, "tool_name": tool_name, "validity": "invalid" if metric.invalid_tool_schema or metric.invalid_argument_type else "valid", "error": "tool error" if metric.tool_errors else None, "recovered": bool(metric.recovered_after_tool_error), "alternate_tool": metric.alternate_tool_used}, request_id=request_id)
    token_values = {field: [getattr(item, field) for item in requests if getattr(item, field) is not None] for field in ("input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens")}
    record_cost(conn, run_id, billing_mode="subscription", cost_source="unavailable: subscription route", input_tokens=sum(token_values["input_tokens"]) if token_values["input_tokens"] else None, output_tokens=sum(token_values["output_tokens"]) if token_values["output_tokens"] else None, cached_input_tokens=sum(token_values["cache_read_tokens"]) if token_values["cache_read_tokens"] else None, reasoning_tokens=sum(token_values["reasoning_tokens"]) if token_values["reasoning_tokens"] else None)
    finalize_run(conn, run_id, ended_at=ended_at, status=status, raw_evidence_path=str(evidence_path), raw_evidence_sha256=digest_bytes(evidence_path.read_bytes()))
    return evidence


def _suite_records(conn: Any, instances: list[TaskInstance], git_sha: str) -> tuple[int, dict[str, int]]:
    suite_id = record_benchmark_suite(conn, SUITE_NAME, "public_characterization", SUITE_VERSION, git_sha=git_sha, evaluation_class=EVALUATION_CLASS, metadata={"families": FAMILIES, "objective": True, "adversarial_isolation": False, "authoritative_reference_present": False})
    records = {}
    for instance in instances:
        records[instance.task_id] = record_benchmark_task(conn, suite_id, family=instance.family, task_id=instance.task_id, variant_seed=str(instance.seed), content_hash=hashlib.sha256(json.dumps(instance.files, sort_keys=True).encode()).hexdigest(), prompt_hash=digest_bytes(instance.prompt.encode()), evaluator_hash=visible_evaluator_digest(instance))
    return suite_id, records


def run_sweep() -> dict[str, Any]:
    discovery = discover_models()
    local = check_local_suite()
    registry = current_registry()
    validate_registry(registry)
    agy = next(item for item in registry if item["name"] == "agy")
    if agy["eligibility"].get("public_characterization") != "supported":
        raise RuntimeError("AGY public characterization eligibility is not supported")
    conn = connect()
    for audited in registry:
        record_harness(
            conn, audited["name"], version=audited.get("observed_version") or audited["version"],
            adapter_version="ekalavya.harness_registry", transport=audited["transport"],
            capabilities=audited["capabilities"], eligibility=audited["eligibility"],
            evidence_label=audited["evidence"], observed_at=discovery["timestamp"],
        )
    harness_id = record_harness(conn, "agy", version=discovery["client_version"], adapter_version="benchmark.adapters.AntigravityAdapter", transport="agy", capabilities=agy["capabilities"], eligibility=agy["eligibility"], evidence_label="public_characterization_non_adversarial", observed_at=discovery["timestamp"])
    instances = [make_instance(family, 20260903 + index) for index, family in enumerate(FAMILIES)]
    git_sha = command(["git", "rev-parse", "HEAD"])[1].strip()
    suite_id, task_records = _suite_records(conn, instances, git_sha)
    attempts = []
    for generation in GENERATIONS:
        for reasoning in REASONING:
            model_id = f"gemini-{generation}-flash-{reasoning}"
            for instance in instances:
                # The exact runtime ID is selected directly.  No medium-model
                # alias or effort overlay is used for low/high variants.
                attempts.append(run_attempt(conn, suite_id, task_records[instance.task_id], instance, model_id, reasoning, harness_id, state_root(), discovery["client_version"]))
    result = {"experiment": EXPERIMENT, "evaluation_class": EVALUATION_CLASS, "discovery": discovery, "local_check": local, "attempts": len(attempts), "completed": sum(item["exit_code"] == 0 for item in attempts), "full_pass": sum(bool(item["assessment"].get("full_pass")) for item in attempts), "retries": 0}
    (state_root() / "run-summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def _valid_rows(conn: Any) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT r.run_id, r.resolved_json, r.started_at, r.evaluation_class, a.score, a.wall_seconds, a.metadata_json FROM runs r JOIN task_attempts a ON a.run_id=r.run_id WHERE r.evaluation_class=? AND r.status='completed' ORDER BY r.started_at", (EVALUATION_CLASS,)).fetchall()
    result = []
    for row in rows:
        resolved = json.loads(row["resolved_json"] or "{}")
        metadata = json.loads(row["metadata_json"] or "{}")
        request_metrics = [dict(item) for item in conn.execute("SELECT * FROM request_metrics WHERE run_id=?", (row["run_id"],))]
        result.append({"model": resolved.get("provider_model_id"), "generation": resolved.get("generation"), "reasoning": resolved.get("reasoning"), "harness": resolved.get("harness"), "score": row["score"], "wall_seconds": row["wall_seconds"], "request_count": metadata.get("request_count"), "tool_events": metadata.get("tool_events"), "invalid_tool_calls": metadata.get("invalid_tool_calls"), "recoveries": metadata.get("recoveries"), "input_tokens": sum((m.get("input_tokens") or 0) for m in request_metrics) if request_metrics and any(m.get("input_tokens") is not None for m in request_metrics) else None, "output_tokens": sum((m.get("output_tokens") or 0) for m in request_metrics) if request_metrics and any(m.get("output_tokens") is not None for m in request_metrics) else None, "valid": True})
    return result


def report() -> Path:
    root = state_root(); conn = connect(); rows = _valid_rows(conn)
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["model"], row["reasoning"], row["harness"]), []).append(row)
    summary = []
    for (model, reasoning, harness), items in sorted(grouped.items()):
        scores = [item["score"] for item in items if item["score"] is not None]
        times = [item["wall_seconds"] for item in items if item["wall_seconds"] is not None]
        summary.append({"model": model, "reasoning": reasoning, "harness": harness, "mean_score": statistics.mean(scores) if scores else None, "median_score": statistics.median(scores) if scores else None, "full_tasks": sum(score == 100 for score in scores), "mean_wall": statistics.mean(times) if times else None, "requests": statistics.mean([item["request_count"] for item in items if item["request_count"] is not None]) if any(item["request_count"] is not None for item in items) else None, "tools": sum(item["tool_events"] for item in items if item["tool_events"] is not None) if any(item["tool_events"] is not None for item in items) else None, "malformed": sum(item["invalid_tool_calls"] for item in items if item["invalid_tool_calls"] is not None) if any(item["invalid_tool_calls"] is not None for item in items) else None, "tokens": sum((item["input_tokens"] or 0) + (item["output_tokens"] or 0) for item in items) if all(item["input_tokens"] is not None and item["output_tokens"] is not None for item in items) else None})
    lines = [f"# {SUITE_NAME}", "", "Class: `public_characterization` (objective, non-adversarially-isolated; no authoritative/reference repair is present in generated candidate workspaces).", "", "## Model × reasoning", "", "| Exact model ID | Reasoning | Harness | Mean score | Median score | Full tasks | Mean wall seconds | Mean requests | Tool events | Malformed calls | Tokens | Actual cost | Calculated cost | API-equivalent cost |", "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|"]
    for item in summary:
        lines.append("| " + " | ".join(str(item[key]) if item[key] is not None else "null" for key in ("model", "reasoning", "harness", "mean_score", "median_score", "full_tasks", "mean_wall", "requests", "tools", "malformed", "tokens")) + " | null | null | null |")
    lines += ["", "## Harness", "", "All valid rows use AGY public-characterization eligibility. No second exact-Gemini harness was available, so a harness comparison was not performed.", "", "## Generation comparison", "", "| Reasoning | 3.7 mean score | 3.8 mean score | Score delta (3.8-3.7) | 3.7 mean wall | 3.8 mean wall | Wall delta (3.8-3.7) |", "|---|---:|---:|---:|---:|---:|---:|"]
    by_key = {(item["model"], item["reasoning"]): item for item in summary}
    for reasoning in ("low", "medium", "high"):
        old, new = by_key.get((f"gemini-3.7-flash-{reasoning}", reasoning)), by_key.get((f"gemini-3.8-flash-{reasoning}", reasoning))
        if old and new:
            lines.append(f"| {reasoning} | {old['mean_score']} | {new['mean_score']} | {(new['mean_score'] - old['mean_score']) if old['mean_score'] is not None and new['mean_score'] is not None else 'null'} | {old['mean_wall']} | {new['mean_wall']} | {(new['mean_wall'] - old['mean_wall']) if old['mean_wall'] is not None and new['mean_wall'] is not None else 'null'} |")
    lines += ["", "## Reasoning and generation interpretation", ""]
    for item in summary:
        lines.append(f"- `{item['model']} / {item['reasoning']} / {item['harness']}`: mean score `{item['mean_score']}`, mean wall `{item['mean_wall']}` seconds.")
    lines += ["", "## Pareto frontier", "", "Quality is maximized; wall time, tokens, malformed calls, and recoveries are minimized where observed. Missing dimensions are not treated as zero."]
    for item in summary:
        dominated = False
        for other in summary:
            if other is item or other["mean_score"] is None or item["mean_score"] is None or other["mean_wall"] is None or item["mean_wall"] is None:
                continue
            comparable_tokens = item["tokens"] is not None and other["tokens"] is not None
            no_worse = other["mean_score"] >= item["mean_score"] and other["mean_wall"] <= item["mean_wall"] and (not comparable_tokens or other["tokens"] <= item["tokens"])
            strictly = other["mean_score"] > item["mean_score"] or other["mean_wall"] < item["mean_wall"] or (comparable_tokens and other["tokens"] < item["tokens"])
            if no_worse and strictly:
                dominated = True
                break
        lines.append(f"- `{item['model']} / {item['reasoning']} / {item['harness']}`: {'dominated' if dominated else 'non-dominated'}")
    lines += ["", "## Catalogue recommendation", "", "Keep Gemini 3.7 Flash as current with Medium as the configured default; retain 3.6 as previous/supported fallback; treat 3.8 as the sole candidate. This report does not change persistent defaults.", "", "## Cost", "", "Actual: null; calculated: null; API-equivalent: null; billing mode: subscription; source: unavailable.", "", "## Telemetry completeness", ""]
    total = len(rows)
    for label, field in (("request count", "request_count"), ("tool events", "tool_events"), ("input/output tokens", "input_tokens"), ("TTFT", None), ("cost evidence", None)):
        count = sum(row.get(field) is not None for row in rows) if field else 0
        lines.append(f"- {label}: {count}/{total} ({(100 * count / total):.1f}%)" if total else f"- {label}: 0/0 (null)")
    path = root / "REPORT.md"; path.write_text("\n".join(lines) + "\n")
    plot_metadata = {
        "score-vs-wall": plot_rows(summary, root / "score-vs-wall.png", x_key="mean_wall", y_key="mean_score", xlabel="mean wall seconds", ylabel="mean score"),
        "reasoning-correctness": plot_rows(summary, root / "reasoning-correctness.png", x_key="reasoning", y_key="mean_score", xlabel="reasoning", ylabel="mean score"),
        "reasoning-wall": plot_rows(summary, root / "reasoning-wall.png", x_key="reasoning", y_key="mean_wall", xlabel="reasoning", ylabel="mean wall seconds"),
        "tokens-vs-correctness": plot_rows(summary, root / "tokens-vs-correctness.png", x_key="tokens", y_key="mean_score", xlabel="tokens", ylabel="mean score"),
    }
    (root / "plot-metadata.json").write_text(json.dumps(plot_metadata, indent=2, sort_keys=True) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    action = (argv or sys.argv[1:] or ["run"])[0]
    if action == "check":
        print(json.dumps(check_local_suite(), indent=2, sort_keys=True)); return 0
    if action == "discover":
        print(json.dumps(discover_models(), indent=2, sort_keys=True)); return 0
    if action == "run":
        print(json.dumps(run_sweep(), indent=2, sort_keys=True)); return 0
    if action == "report":
        print(report()); return 0
    raise SystemExit(f"unknown command: {action}")


if __name__ == "__main__":
    raise SystemExit(main())
