"""Narrow execution bridge for explicitly configured legacy delegate routes."""

from __future__ import annotations

from pathlib import Path

from delegation.core import run_consultation


def execute(resolution: dict, prompt_file: Path, workspace: Path, *, primary: str | None = None) -> dict[str, object]:
    """Execute only a route named in the resolved catalogue entry.

    Ekalavya V1 does not invent a provider adapter. A catalogue entry may carry
    ``legacy_route`` (for example ``flash``); that route is passed to the
    existing safety-hardened wrapper, which enforces scope, depth, stdin,
    timeout, process cleanup, and response retention. Missing route metadata
    is a deterministic harness-unavailable result.
    """
    candidate = resolution.get("resolved") or {}
    route = candidate.get("legacy_route")
    if not route:
        return {"state": "harness-unavailable", "reason": "resolved candidate has no configured execution adapter"}
    task = prompt_file.read_text(encoding="utf-8")
    code, evidence = run_consultation(route, workspace, task, primary=primary, caller="ekalavya")
    return {"state": "completed" if code == 0 else "failed", "exit_code": code, "evidence": str(evidence)}
