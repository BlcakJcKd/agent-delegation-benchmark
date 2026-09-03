"""Offline audit artifact generation for retained public-characterization evidence."""

from __future__ import annotations

import csv
import json
import sqlite3
import statistics
from pathlib import Path
from typing import Any

from ekalavya.ledger import connect, default_db_path

from . import FAMILIES, SUITE_NAME, SUITE_VERSION


def _evidence(state: Path) -> list[dict[str, Any]]:
    items = []
    for path in sorted((state / "evidence").glob("*.json")):
        item = json.loads(path.read_text())
        item["evidence_file"] = path.name
        items.append(item)
    return sorted(items, key=lambda item: item["started_at"])


def _db_rows() -> dict[str, dict[str, Any]]:
    conn = sqlite3.connect(f"file:{default_db_path()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    query = """
    SELECT r.run_id, r.status, a.score, a.wall_seconds,
           json_extract(r.resolved_json,'$.provider_model_id') model,
           json_extract(r.resolved_json,'$.reasoning') reasoning,
           bt.family,
           rm.input_tokens, rm.output_tokens, rm.cache_read_tokens, rm.reasoning_tokens
      FROM runs r JOIN task_attempts a ON a.run_id=r.run_id
      JOIN benchmark_tasks bt ON bt.id=a.task_id
      LEFT JOIN request_metrics rm ON rm.run_id=r.run_id
     WHERE r.evaluation_class='public_characterization'
    """
    result = {}
    for row in conn.execute(query):
        result[row["run_id"]] = dict(row)
    return result


def _matrix(items: list[dict[str, Any]], db: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in items:
        assessment = item.get("assessment", {})
        checks = assessment.get("checks", [])
        record = db.get(item["run_id"], {})
        scored = item.get("exit_code") == 0 and not item.get("timed_out", False)
        row = {
            "model": item["resolved"].get("provider_model_id"),
            "reasoning": item["resolved"].get("reasoning"),
            "task": item["task"].get("family"),
            "terminal_status": record.get("status") or ("completed" if scored else "harness_failure"),
            "score": record.get("score") if scored else None,
            "full_pass": assessment.get("full_pass") if scored else None,
            "wall_seconds": item.get("wall_seconds"),
            "passed_checks": sum(bool(check.get("passed")) for check in checks),
            "input_tokens": record.get("input_tokens"),
            "output_tokens": record.get("output_tokens"),
            "cache_read_tokens": record.get("cache_read_tokens"),
            "reasoning_tokens": record.get("reasoning_tokens"),
        }
        for index, check in enumerate(checks, 1):
            row[f"check_{index}"] = "pass" if check.get("passed") else "fail"
            row[f"check_{index}_name"] = check.get("name")
        rows.append(row)
    return rows


def _matrix_markdown(rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Task × check matrix", "",
        "`—` means no correctness score was assigned because the attempt did not complete successfully.", "",
        "| Model | Reasoning | Task | Status | C1 | C2 | C3 | C4 | C5 | C6 | C7 | C8 | Passed | Score | Full pass | Wall s |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---:|---:|---|---:|",
    ]
    for row in rows:
        cells = [row.get(f"check_{i}", "—") for i in range(1, 9)]
        lines.append("| " + " | ".join([str(row["model"]), str(row["reasoning"]), str(row["task"]), str(row["terminal_status"]), *cells, str(row["passed_checks"]), str(row["score"] if row["score"] is not None else "—"), str(row["full_pass"] if row["full_pass"] is not None else "—"), f"{row['wall_seconds']:.3f}"]) + " |")
    lines += ["", "## Check names by task", ""]
    for task in FAMILIES:
        row = next(row for row in rows if row["task"] == task)
        lines.append(f"- `{task}`: " + ", ".join(row.get(f"check_{i}_name", "") for i in range(1, 9)))
    return "\n".join(lines)


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for task in FAMILIES:
        group = [row for row in rows if row["task"] == task and row["score"] is not None]
        scores = [row["score"] for row in group]
        checks = {}
        for index in range(1, 9):
            values = [row[f"check_{index}"] == "pass" for row in group]
            checks[group[0][f"check_{index}_name"] if group else f"check_{index}"] = sum(values) / len(values) if values else None
        result[task] = {"mean": statistics.mean(scores) if scores else None, "median": statistics.median(scores) if scores else None, "min": min(scores) if scores else None, "max": max(scores) if scores else None, "full_solves": sum(row["full_pass"] is True for row in group), "scored": len(group), "attempted": sum(row["task"] == task for row in rows), "check_pass_rates": checks}
    return result


def generate_audit_artifacts(state: Path) -> dict[str, str]:
    state = state.resolve()
    items = _evidence(state)
    db = _db_rows()
    rows = _matrix(items, db)
    fieldnames = ["model", "reasoning", "task", "terminal_status", *[f"check_{i}" for i in range(1, 9)], "passed_checks", "score", "full_pass", "wall_seconds", "input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens"]
    with (state / "task-check-matrix.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows({key: row.get(key) for key in fieldnames} for row in rows)
    (state / "task-check-matrix.md").write_text(_matrix_markdown(rows) + "\n")

    correction = {"originally_recorded_suite_sha": "91f96127f9393cc81e4f4c296ec5d8e228210a13", "corrected_suite_sha": "738a8aa26d87d266af34c2af8e70577bb0bb60dd", "correction_reason": "Recorded SHA predates the tracked public-characterization implementation.", "correction_timestamp": None, "ledger_correction_id": None}
    conn = connect()
    suite = conn.execute("SELECT id,git_sha FROM benchmark_suites WHERE name=? AND version=?", (SUITE_NAME, SUITE_VERSION)).fetchone()
    if suite:
        correction_row = conn.execute("SELECT id,originally_recorded_git_sha,corrected_git_sha,corrected_at,reason FROM benchmark_suite_corrections WHERE suite_id=? ORDER BY id DESC LIMIT 1", (suite[0],)).fetchone()
        if correction_row:
            correction.update({"ledger_correction_id": correction_row[0], "originally_recorded_suite_sha": correction_row[1], "corrected_suite_sha": correction_row[2], "correction_timestamp": correction_row[3], "correction_reason": correction_row[4]})
    (state / "provenance").mkdir(exist_ok=True)
    (state / "provenance/correction-summary.json").write_text(json.dumps(correction, indent=2, sort_keys=True) + "\n")
    (state / "telemetry-semantics.md").write_text("""# AGY telemetry semantics

AGY 1.1.25 produced one parsed outer session/result record per attempt. This is recorded as `request_metric_semantics: harness_session`, not `provider_model_request`. The parsed record did not expose a provider/model ID, request boundaries, or TTFT.

`tool_events: 0` in historical raw evidence is not an observable zero. The parser had no independently attachable AGY tool trace, so review reporting uses `tool_event_telemetry: unavailable` and reports tool counts as null. No provider inference is made.
""")
    token_lines = ["# Token semantics", "", "The reported totals are sums across task attempts of AGY-reported usage fields from one parsed outer record per attempt. They are not verified provider billing tokens.", "", "| Model | Reasoning | Input | Output | Cache read | Reasoning | Input+output |", "|---|---|---:|---:|---:|---:|---:|"]
    grouped = {}
    for row in rows:
        key = (row["model"], row["reasoning"]); grouped.setdefault(key, []).append(row)
    for key, group in sorted(grouped.items()):
        sums = {field: sum(row[field] or 0 for row in group) for field in ("input_tokens", "output_tokens", "cache_read_tokens", "reasoning_tokens")}
        token_lines.append(f"| {key[0]} | {key[1]} | {sums['input_tokens']} | {sums['output_tokens']} | {sums['cache_read_tokens']} | {sums['reasoning_tokens']} | {sums['input_tokens'] + sums['output_tokens']} |")
    token_lines += ["", "## Per-attempt distribution", "", "| Model | Reasoning | Task | Input | Output | Cache read | Reasoning | Input+output |", "|---|---|---|---:|---:|---:|---:|---:|"]
    for row in rows:
        input_tokens = row["input_tokens"]
        output_tokens = row["output_tokens"]
        total_tokens = input_tokens + output_tokens if input_tokens is not None and output_tokens is not None else None
        token_lines.append(f"| {row['model']} | {row['reasoning']} | {row['task']} | {input_tokens if input_tokens is not None else 'null'} | {output_tokens if output_tokens is not None else 'null'} | {row['cache_read_tokens'] if row['cache_read_tokens'] is not None else 'null'} | {row['reasoning_tokens'] if row['reasoning_tokens'] is not None else 'null'} | {total_tokens if total_tokens is not None else 'null'} |")
    token_lines += ["", "The cache-read values exceed input values and have no verified billing/session definition in retained evidence. No duplicated event stream was retained; duplicate accounting therefore cannot be ruled out beyond the single parsed record per attempt."]
    (state / "token-semantics.md").write_text("\n".join(token_lines) + "\n")

    stats = _stats(rows)
    task_lines = ["## Per-task score distributions and check pass rates", "", "Rates use scored attempts as the denominator; attempted counts retain the failed harness row."]
    for task in FAMILIES:
        item = stats[task]
        rates = "; ".join(f"{name}: {rate * 100:.1f}%" for name, rate in item["check_pass_rates"].items())
        task_lines.append(f"- `{task}`: mean/median/min/max `{item['mean']}/{item['median']}/{item['min']}/{item['max']}`, full solves `{item['full_solves']}`, scored/attempted `{item['scored']}/{item['attempted']}`. Check pass rates — {rates}.")
    audit_lines = ["# Public Characterization V1 Audit", "", "## A. PROVENANCE", "", f"Recorded suite SHA: `{correction['originally_recorded_suite_sha']}`.", f"Actual authoritative suite SHA: `{correction['corrected_suite_sha']}`.", "Correction necessary: yes. Raw evidence was preserved; the ledger correction is append-only.", "", "## B. COMPLETE TASK × CHECK MATRIX", "", "See `task-check-matrix.md` and `task-check-matrix.csv`; they contain one row per attempt and all eight outcomes.", "", "## C. COMMON FAILURE PATTERNS", "", "All six configurations have the same scored pattern: P1 50, P2 87.5, P3 50, P4 87.5. The five non-failed configurations therefore have mean 68.75 and fail exactly the same checks.", "", "## D. TASK/CHECK DISCRIMINATION", "", "P1 and P3 are common-failure modes with four universal failures each. P2 and P4 are apparently too easy overall, with one universal failure each. No check distinguishes configurations in this sample. No evaluator/generator defect is evidenced in task semantics.", "", *task_lines, "", "## E. TIMEOUT / RELIABILITY SEMANTICS", "", "Gemini 3.8 High P2 ended at 302.632 seconds with exit code 1 and harness_failure status. The wrapper timed_out flag is false, so the evidence supports a timeout-like harness failure, not an explicit wrapper timeout. Quality is 62.5 conditional on its three completed tasks; reliability is 3/4 (75%). No correctness zero is assigned.", "", "## F. AGY REQUEST SEMANTICS", "", "One request record means one parsed AGY outer session/result record, not one verified provider model invocation.", "", "## G. AGY TOOL TELEMETRY SEMANTICS", "", "Tool activity is unavailable, not observable zero. The parser captured no tool events and AGY exposes no independent candidate-tool subprocess trace in retained evidence.", "", "## H. TOKEN SEMANTICS", "", "See `token-semantics.md`. Values are AGY-reported usage fields with uncertain cumulative/session semantics, not provider billing tokens; direct cross-model comparison is limited.", "", "## I. PUBLIC-CHARACTERIZATION CONTAMINATION CHECK", "", "The public generator/evaluator contains no exact public reference repair. The V2 reference fixer targets different task families. No full authoritative P1–P4 solution exists in retained candidate workspaces. Because AGY is not filesystem-contained, absence of access to host material cannot be proven; classify the screen as non-adversarial exposure-limited, not hidden-isolated.", "", "## J. CORRECTED PARETO INTERPRETATION", "", "3.8 Low is first-pass non-dominated on observed quality, wall time, and reported usage with full completion. 3.7 Low dominates 3.7 Medium/High on this screen, but is itself a comparison baseline rather than a promotion decision. 3.8 Medium/High are not attractive for further testing here; High also has 75% completion.", "", "## K. DEFAULT INTERPRETATION", "", "Keep the persistent default at Gemini 3.7 Flash Medium. 3.7 Low has equal observed correctness with lower wall time and reported usage, but one four-task repetition is insufficient to change the user-owned default. Do not promote Gemini 3.8.", "", "## L. RECOMMENDED NEXT EXPERIMENT", "", "First fix/version the suite. Do not run characterization during this audit. Afterward use harder variants of the same four families, three matched repetitions, and retain 3.7 Low, 3.7 Medium, and 3.8 Low. Use matched seeds per repetition; do not automatically retest 3.8 Medium/High.", "", "## M. TESTS", "", "Recorded by the implementation handoff after running the requested no-model checks.", "", "## N. PRIVACY", "", "Review bundle uses an allowlist, excludes config/ledger/credentials/workspaces/raw provider traces, and sanitizes irrelevant absolute user-state paths in the review copy only.", "", "## O. GIT", "", "No private evidence or generated bundle is to be committed."]
    (state / "AUDIT_REPORT.md").write_text("\n".join(audit_lines) + "\n")
    return {"matrix_csv": str(state / "task-check-matrix.csv"), "matrix_md": str(state / "task-check-matrix.md"), "audit_report": str(state / "AUDIT_REPORT.md"), "correction": str(state / "provenance/correction-summary.json")}
