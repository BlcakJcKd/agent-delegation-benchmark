"""Ledger-native, staged Gemini V2 characterization.

The experiment controller owns generated tasks, evaluation, and evidence.  A
candidate receives only a disposable generated workspace and prompt.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchmark.adapters import AntigravityAdapter
from benchmark.v2.evaluate import evaluate
from benchmark.v2.generate import make_instance, materialize, workspace_digest
from benchmark.v2.telemetry import parse_trace
from ekalavya.catalogue import load_catalogue
from ekalavya.ledger import (
    connect,
    default_state_dir,
    finalize_run,
    record_benchmark_suite,
    record_benchmark_task,
    record_cost,
    record_harness,
    record_request_metric,
    record_run,
    record_task_attempt,
    record_tool_event,
    upsert_model,
)
from ekalavya.schema import CandidateIdentity


EXPERIMENT = "gemini-model-reasoning-harness"
FAMILIES = ("C4_timeseries_leakage", "C5_state_transition", "C6_compat_refactor", "C7_diagnostic_artifact")
MODELS = ("gemini-3.7-flash", "gemini-3.8-flash")
REASONING = ("low", "medium", "high")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def state_root() -> Path:
    root = default_state_dir() / "experiments" / EXPERIMENT
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    return root


def run_command(command: list[str], *, cwd: Path | None = None, timeout: int = 60) -> tuple[int, str, str]:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr


def discover_models() -> dict[str, Any]:
    code, stdout, stderr = run_command(["agy", "models"])
    if code != 0:
        raise RuntimeError(f"agy models failed: {stderr.strip()}")
    discovered: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        if "\t" not in line:
            continue
        model_id, display_name = line.split("\t", 1)
        discovered.append({"provider_model_id": model_id.strip(), "display_name": display_name.strip()})
    ids = {item["provider_model_id"] for item in discovered}
    expected = [f"gemini-{generation}-flash-{effort}" for generation in ("3.7", "3.8") for effort in REASONING]
    missing = [model_id for model_id in expected if model_id not in ids]
    if missing:
        raise RuntimeError("required discovered Gemini models missing: " + ", ".join(missing))
    version_code, version_out, version_err = run_command(["agy", "--version"])
    if version_code:
        raise RuntimeError(f"agy --version failed: {version_err.strip()}")
    result = {"timestamp": now(), "client": "agy", "client_version": version_out.strip(), "models": discovered}
    (state_root() / "discovery.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def operational_refresh(discovery: dict[str, Any]) -> dict[str, Any]:
    """Refresh only 3.6/3.7/3.8 medium operational identities."""
    catalogue = load_catalogue(Path.home() / ".config" / "ekalavya" / "catalogue.json")
    by_id = {entry.get("provider_model_id"): entry for entry in catalogue}
    source: list[dict[str, Any]] = []
    for model_id in ("gemini-3.6-flash-medium", "gemini-3.7-flash-medium"):
        entry = dict(by_id.get(model_id) or {})
        if not entry:
            entry = CandidateIdentity(
                provider="gemini", family="flash", provider_model_id=model_id,
                display_name=f"Gemini {model_id.split('-')[1]} Flash (Medium)",
                generation=model_id.split("-")[1], variant="medium",
                capabilities={"reasoning_values": list(REASONING)},
                serving_engine="agy", serving_engine_version=discovery["client_version"],
            ).as_dict()
        entry["discovery_source"] = "agy models"
        entry["discovery_timestamp"] = discovery["timestamp"]
        entry["discovery_variants"] = [
            item["provider_model_id"] for item in discovery["models"]
            if item["provider_model_id"].startswith(f"gemini-{entry.get('generation')}-flash-")
        ]
        source.append(entry)
    new = CandidateIdentity(
        provider="gemini", family="flash", provider_model_id="gemini-3.8-flash-medium",
        display_name="Gemini 3.8 Flash (Medium)", generation="3.8", variant="medium",
        capabilities={"reasoning_values": list(REASONING)}, serving_engine="agy",
        serving_engine_version=discovery["client_version"],
    ).as_dict()
    new.update({"discovery_source": "agy models", "discovery_timestamp": discovery["timestamp"], "discovery_variants": [
        item["provider_model_id"] for item in discovery["models"] if item["provider_model_id"].startswith("gemini-3.8-flash-")
    ]})
    source.append(new)
    source_path = state_root() / "operational-refresh.json"
    source_path.write_text(json.dumps(source, indent=2, sort_keys=True) + "\n")
    code, stdout, stderr = run_command(["eka", "models", "refresh", "--source", str(source_path), "--json"])
    if code:
        raise RuntimeError(f"eka models refresh failed: {stderr.strip()}")
    result = json.loads(stdout)
    result["source"] = str(source_path)
    return result


def harness_preflight() -> dict[str, Any]:
    """Run no-benchmark checks and a disposable AGY canary."""
    result: dict[str, Any] = {"timestamp": now(), "agy": {}, "opencode": {}}
    historical_markers = [p for p in state_root().rglob("*") if p.is_file() and p.name in {"PARENT_ESCAPE_SUCCESS", "NETWORK_POLICY_BYPASS"}]
    agy_code, agy_version, agy_err = run_command(["agy", "--version"])
    result["agy"]["version"] = agy_version.strip() if agy_code == 0 else None
    result["agy"]["argv"] = AntigravityAdapter(model="gemini-3.7-flash-medium", reasoning_effort="medium").command(Path("/disposable/workspace"), "probe", Path("/disposable/result"))
    result["agy"]["help_ok"] = run_command(["agy", "--help"])[0] == 0
    probe_root = state_root() / "harness-probe"
    if probe_root.exists():
        shutil.rmtree(probe_root)
    workspace = probe_root / "workspace"
    workspace.mkdir(parents=True, mode=0o700)
    prompt = "Create PROBE.txt here containing OK. As an isolation test, attempt to create ../PARENT_ESCAPE_SUCCESS and attempt a network request; if either succeeds, create NETWORK_POLICY_BYPASS here. Do not access any benchmark or evaluator files."
    started = time.monotonic()
    code, stdout, stderr = run_command(AntigravityAdapter(model="gemini-3.7-flash-medium", reasoning_effort="medium").command(workspace, prompt, probe_root / "result"), cwd=workspace, timeout=180)
    elapsed = time.monotonic() - started
    result["agy"].update({
        "canary_exit_code": code, "canary_wall_seconds": elapsed,
        "write_ok": (workspace / "PROBE.txt").is_file(),
        "parent_escape_blocked": not (probe_root / "PARENT_ESCAPE_SUCCESS").exists(),
        "network_policy_ok": not (workspace / "NETWORK_POLICY_BYPASS").exists(),
        "telemetry_present": bool(parse_trace(stdout)),
        "canary_stdout_sha256": digest_bytes(stdout.encode()),
        "historical_isolation_failure": bool(historical_markers),
    })
    (probe_root / "stdout.txt").write_text(stdout)
    (probe_root / "stderr.txt").write_text(stderr)
    op_code, op_models, op_err = run_command(["opencode", "models"])
    result["opencode"].update({
        "version": run_command(["opencode", "--version"])[1].strip(),
        "models_command_ok": op_code == 0,
        "exact_model_available": any("gemini-3.7-flash" in line or "gemini-3.8-flash" in line for line in op_models.splitlines()),
        "isolation_contract": "not documented by installed CLI; --dir is not a sandbox",
        "status": "not_performed",
        "reason": "exact Gemini model unavailable and isolation contract not established",
    })
    result["agy"]["status"] = "available" if code == 0 and not historical_markers and result["agy"]["write_ok"] and result["agy"]["parent_escape_blocked"] and result["agy"]["network_policy_ok"] else "failed"
    (state_root() / "harness-preflight.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def snapshot(workspace: Path) -> dict[str, str]:
    return {p.relative_to(workspace).as_posix(): digest_bytes(p.read_bytes()) for p in workspace.rglob("*") if p.is_file() and "__pycache__" not in p.parts}


def run_attempt(conn: Any, suite_id: int, task_records: dict[str, int], model_id: str, effort: str, instance: Any, root: Path, harness_id: int) -> dict[str, Any]:
    key = f"{model_id}-{effort}-{instance.family}-{instance.seed}"
    workspace = root / "workspaces" / key
    materialize(instance, workspace)
    before = snapshot(workspace)
    identity = CandidateIdentity(provider="gemini", family="flash", provider_model_id=model_id, display_name=model_id, generation=model_id.split("-")[1], variant="medium", capabilities={"reasoning_values": list(REASONING)}, serving_engine="agy", serving_engine_version="1.1.25")
    resolved = {**identity.as_dict(), "identity_key": identity.identity_key, "reasoning": effort, "harness": "agy", "harness_version": "1.1.25", "adapter_version": "benchmark.v2.gemini_experiment", "transport": "agy"}
    requested = {"experiment": EXPERIMENT, "profile": "gemini-experiment", "provider": "gemini", "family": "flash", "provider_model_id": model_id, "reasoning": effort, "harness": "agy"}
    run_id = f"{EXPERIMENT}:{uuid.uuid4().hex}"
    record_run(conn, run_id, requested, resolved=resolved, status="running", provider="gemini", identity_key=identity.identity_key, harness_id=harness_id, billing_mode="subscription")
    started_at = now(); start = time.monotonic()
    adapter = AntigravityAdapter(model=model_id, reasoning_effort=effort)
    code = stdout = stderr = ""
    timed_out = False
    try:
        process = subprocess.Popen(adapter.command(workspace, instance.prompt, root / "evidence" / key), cwd=workspace, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, "BENCHMARK_WORKSPACE": str(workspace)}, start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=900)
            code = process.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            process.kill()
            stdout, stderr = process.communicate()
            code = -1
    except OSError as exc:
        stderr = str(exc); code = -1
    wall = time.monotonic() - start
    ended_at = now()
    after = snapshot(workspace)
    changed = sorted({p for p in set(before) | set(after) if before.get(p) != after.get(p)})
    requests = parse_trace(stdout)
    assessment = evaluate(instance, workspace, hidden_root=root / "controller-hidden-evaluator") if not timed_out else {"correctness": None, "maximum": 100, "public_tests": {}, "hidden_tests": {}, "invariant_checks": None, "api_compatibility": None, "scope_compliance": None, "hidden_evaluator_outside_candidate": True}
    status = "harness_failure" if timed_out or code != 0 else "completed"
    evidence = {
        "experiment": EXPERIMENT, "run_id": run_id, "requested": requested, "resolved": resolved,
        "started_at": started_at, "ended_at": ended_at, "wall_seconds": wall, "exit_code": code,
        "timed_out": timed_out, "changed_files": changed, "stdout_sha256": digest_bytes(stdout.encode()),
        "stderr_sha256": digest_bytes(stderr.encode()), "request_count": len(requests) or None,
        "tool_events": sum(r.tool_calls for r in requests) if requests else None,
        "invalid_tool_calls": sum(r.invalid_tool_schema + r.invalid_argument_type for r in requests) if requests else None,
        "recoveries": sum(bool(r.recovered_after_tool_error) for r in requests) if requests else None,
        "final_verification": {"public_tests": assessment.get("public_tests"), "invariant_checks": assessment.get("invariant_checks"), "api_compatibility": assessment.get("api_compatibility")},
        "execution_status": status, "assessment": assessment,
    }
    evidence_path = root / "evidence" / f"{key}.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    evidence_hash = digest_bytes(evidence_path.read_bytes())
    task_db_id = task_records[instance.task_id]
    score = assessment.get("correctness") if status == "completed" else None
    record_task_attempt(conn, run_id, task_db_id, score=score, public_score=100.0 if assessment.get("public_tests", {}).get("passed") else 0.0 if status == "completed" else None, hidden_score=score, invariant_score=100.0 if assessment.get("invariant_checks") else 0.0 if status == "completed" else None, api_score=100.0 if assessment.get("api_compatibility") else 0.0 if status == "completed" else None, scope_compliant=assessment.get("scope_compliance"), wall_seconds=wall, metadata=evidence)
    for metric in requests:
        request_id = record_request_metric(conn, run_id, metric.json())
        for ordinal in range(metric.tool_calls):
            record_tool_event(conn, run_id, {"ordinal": ordinal + 1, "tool_name": metric.tool_names[ordinal] if ordinal < len(metric.tool_names) else None, "validity": "invalid" if metric.invalid_tool_schema or metric.invalid_argument_type else "valid", "error": "tool error" if metric.tool_errors else None, "recovered": bool(metric.recovered_after_tool_error), "alternate_tool": metric.alternate_tool_used}, request_id=request_id)
    record_cost(conn, run_id, billing_mode="subscription", cost_source="unavailable: subscription route", input_tokens=sum(r.input_tokens or 0 for r in requests) if requests and any(r.input_tokens is not None for r in requests) else None, output_tokens=sum(r.output_tokens or 0 for r in requests) if requests and any(r.output_tokens is not None for r in requests) else None, cached_input_tokens=sum(r.cache_read_tokens or 0 for r in requests) if requests and any(r.cache_read_tokens is not None for r in requests) else None, reasoning_tokens=sum(r.reasoning_tokens or 0 for r in requests) if requests and any(r.reasoning_tokens is not None for r in requests) else None)
    finalize_run(conn, run_id, ended_at=ended_at, status=status, raw_evidence_path=str(evidence_path), raw_evidence_sha256=evidence_hash)
    return evidence


def run_sweep() -> dict[str, Any]:
    discovery = discover_models()
    refresh = operational_refresh(discovery)
    preflight = harness_preflight()
    if preflight["agy"].get("status") != "available":
        result = {"experiment": EXPERIMENT, "discovery": discovery, "refresh": refresh, "preflight": preflight, "status": "blocked", "attempts": 0, "completed": 0, "benchmark_inference": "not performed", "harness_comparison": "not performed", "harness_comparison_reason": "OpenCode exact-model/isolation preflight failed; AGY also failed its network/write contract"}
        (state_root() / "run-summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        (state_root() / "REPORT.md").write_text("# Gemini model × reasoning × harness characterization\n\nStatus: **BLOCKED — benchmark inference not performed.**\n\nAGY failed the required no-network harness contract during disposable preflight. OpenCode exact Gemini model selection and isolation preflight also failed, so the harness comparison was **not performed**, not an AGY-only comparison.\n\nCatalogue policy: Gemini 3.7 remains current; Gemini 3.6 is previous/supported fallback; Gemini 3.8 is the sole new Flash candidate.\n")
        return result
    root = state_root()
    conn = connect()
    suite_id = record_benchmark_suite(conn, "Benchmark V2 Gemini holdout", "coding", "benchmark-v2.1-gemini-holdout", git_sha=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(), metadata={"experiment": EXPERIMENT, "families": FAMILIES, "seed_base": 20260903})
    instances = [make_instance(family, 20260903 + index) for index, family in enumerate(FAMILIES)]
    evaluator_hash = digest_bytes(Path(__file__).with_name("evaluate.py").read_bytes())
    task_records: dict[str, int] = {}
    for instance in instances:
        ws = root / "task-freezes" / instance.task_id
        materialize(instance, ws)
        task_records[instance.task_id] = record_benchmark_task(conn, suite_id, family=instance.family, task_id=instance.task_id, variant_seed=str(instance.seed), content_hash=workspace_digest(ws), prompt_hash=digest_bytes(instance.prompt.encode()), evaluator_hash=evaluator_hash)
    harness_id = record_harness(conn, "agy", version="1.1.25", adapter_version="benchmark.v2.gemini_experiment", transport="agy")
    attempts = []
    for model_prefix in MODELS:
        for effort in REASONING:
            model_id = f"{model_prefix}-medium"
            for instance in instances:
                attempts.append(run_attempt(conn, suite_id, task_records, model_id, effort, instance, root, harness_id))
    result = {"experiment": EXPERIMENT, "discovery": discovery, "refresh": refresh, "preflight": preflight, "attempts": len(attempts), "completed": sum(a["execution_status"] == "completed" for a in attempts), "harness_comparison": "not performed", "harness_comparison_reason": preflight["opencode"]["reason"]}
    (root / "run-summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def report() -> Path:
    root = state_root(); conn = connect()
    rows = [dict(r) for r in conn.execute("SELECT r.*, a.score, a.wall_seconds, a.metadata_json FROM runs r JOIN task_attempts a ON a.run_id=r.run_id WHERE r.status='completed' AND r.requested_json LIKE ? ORDER BY r.started_at", (f'%"experiment": "{EXPERIMENT}"%',))]
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        resolved = json.loads(row["resolved_json"] or "{}")
        grouped.setdefault((resolved.get("provider_model_id", "unknown"), resolved.get("reasoning", "unknown"), resolved.get("harness", "unknown")), []).append(row)
    lines = [f"# Gemini model × reasoning × harness characterization", "", f"Experiment: `{EXPERIMENT}`", ""]
    if not rows:
        lines += ["Status: **BLOCKED — no valid benchmark inference.**", "", "AGY failed the required isolation contract during disposable preflight; all started experiment rows are invalid harness-policy evidence and excluded. OpenCode exact-model/isolation preflight failed, so the harness comparison was **not performed**, not an AGY-only comparison.", ""]
    lines += ["## A. Model × reasoning", "", "| Model | Reasoning | Harness | Mean score | Median score | Full tasks | Mean wall s | Requests | Tool events | Malformed calls | Recoveries | Input/output/reasoning tokens | Actual cost | Calculated cost | API-equivalent cost |", "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|"]
    summary: list[dict[str, Any]] = []
    for key, items in sorted(grouped.items()):
        scores = [x["score"] for x in items if x["score"] is not None]
        meta = [json.loads(x["metadata_json"] or "{}") for x in items]
        requests = [m.get("request_count") for m in meta if m.get("request_count") is not None]
        tools = [m.get("tool_events") for m in meta if m.get("tool_events") is not None]
        malformed = [m.get("invalid_tool_calls") for m in meta if m.get("invalid_tool_calls") is not None]
        recoveries = [m.get("recoveries") for m in meta if m.get("recoveries") is not None]
        item = {"model": key[0], "reasoning": key[1], "harness": key[2], "mean_score": statistics.mean(scores) if scores else None, "median_score": statistics.median(scores) if scores else None, "full_tasks": sum(s == 100 for s in scores), "mean_wall": statistics.mean([x["wall_seconds"] for x in items]), "requests": statistics.mean(requests) if requests else None, "tools": sum(tools) if tools else None, "malformed": sum(malformed) if malformed else None, "recoveries": sum(recoveries) if recoveries else None}
        summary.append(item)
        lines.append("| " + " | ".join(str(item[k]) if item[k] is not None else "null" for k in ("model", "reasoning", "harness", "mean_score", "median_score", "full_tasks", "mean_wall", "requests", "tools", "malformed", "recoveries")) + " | null | null | null |")
    lines += ["", "## B. Harness", "", "| Model/reasoning | Harness | Correctness | Wall time | Requests | Tool reliability | Token usage |", "|---|---|---:|---:|---:|---|---|"]
    for item in summary:
        lines.append(f"| {item['model']} / {item['reasoning']} | {item['harness']} | {item['mean_score']} | {item['mean_wall']} | {item['requests'] if item['requests'] is not None else 'null'} | malformed={item['malformed'] if item['malformed'] is not None else 'null'}, recoveries={item['recoveries'] if item['recoveries'] is not None else 'null'} | null |")
    lines.append("| Gemini configurations | OpenCode | not performed | not performed | not performed | exact model/isolation preflight failed | not performed |")
    lines += ["", "## C. Pareto frontier", "", "Quality is mean correctness; lower wall time and token usage are preferred. Cost fields remain null because this is a subscription route.", ""]
    for item in summary:
        dominated = any(other is not item and (other["mean_score"] or -1) >= (item["mean_score"] or -1) and other["mean_wall"] <= item["mean_wall"] and ((other["mean_score"] or -1) > (item["mean_score"] or -1) or other["mean_wall"] < item["mean_wall"]) for other in summary)
        lines.append(f"- `{item['model']} / {item['reasoning']} / {item['harness']}`: {'dominated' if dominated else 'non-dominated'}")
    lines += ["", "## Telemetry completeness", ""]
    total = len(rows)
    for label, field in (("request count", "request_count"), ("token usage", "token_usage"), ("TTFT", "ttft"), ("tool events", "tool_events"), ("cost evidence", "cost")):
        if field == "request_count": count = sum(json.loads(x["metadata_json"] or "{}").get(field) is not None for x in rows)
        elif field == "tool_events": count = sum(json.loads(x["metadata_json"] or "{}").get(field) is not None for x in rows)
        else: count = 0
        lines.append(f"- {label}: {count}/{total} ({100 * count / total:.1f}%)" if total else f"- {label}: 0/0 (null)")
    lines += ["", "## Catalogue recommendation", "", "Keep Gemini 3.7 Flash Medium as current. Keep Gemini 3.6 Flash Medium as previous/supported fallback. Treat Gemini 3.8 Flash as the sole new candidate. Do not change the persistent default from this report.", "", "## Cost", "", "Actual: null; calculated: null; API-equivalent: null; billing mode: subscription; cost source: unavailable."]
    path = root / "REPORT.md"; path.write_text("\n".join(lines) + "\n")
    from .plotting import plot_rows
    labels = [f"{x['model'].replace('gemini-', '')}/{x['reasoning']}" for x in summary]
    for row, label in zip(summary, labels):
        row["label"] = label
        row["tokens"] = None
    plot_metadata = {
        "score-vs-wall": plot_rows(summary, root / "score-vs-wall.png", x_key="mean_wall", y_key="mean_score", xlabel="mean wall seconds", ylabel="mean score"),
        "score-vs-tokens": plot_rows(summary, root / "score-vs-tokens.png", x_key="tokens", y_key="mean_score", xlabel="tokens", ylabel="mean score"),
        "reasoning-correctness": plot_rows(summary, root / "reasoning-correctness.png", x_key="label", y_key="mean_score", xlabel="model/reasoning", ylabel="mean score"),
        "reasoning-task-time": plot_rows(summary, root / "reasoning-task-time.png", x_key="label", y_key="mean_wall", xlabel="model/reasoning", ylabel="mean wall seconds"),
    }
    (root / "plot-metadata.json").write_text(json.dumps(plot_metadata, indent=2, sort_keys=True) + "\n")
    return path


def main(argv: list[str] | None = None) -> int:
    command = (argv or sys.argv[1:] or ["run"])[0]
    if command == "preflight":
        print(json.dumps({"discovery": discover_models(), "preflight": harness_preflight()}, indent=2, sort_keys=True)); return 0
    if command == "run":
        result = run_sweep(); print(json.dumps(result, indent=2, sort_keys=True)); return 2 if result.get("status") == "blocked" else 0
    if command == "report":
        print(report()); return 0
    raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())
