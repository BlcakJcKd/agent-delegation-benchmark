"""Narrow, auditable delegated-consultation command construction and execution.

The default mode is read-only consultation.  It intentionally has no command
for implementation delegation yet: writes need an explicit future scope and
approval design rather than becoming an accidental default.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import routing
from .paths import log_root as _xdg_log_root

READ_ONLY_CLAUDE_TOOLS: tuple[str, ...] = ("Read", "Glob", "Grep")
DEFAULT_TIMEOUT_SECONDS = 300

# Inherited-environment marker that identifies a process already running
# inside a delegated (child) context.  The wrapper rejects any invocation
# where this is already present and >= 1, and always sets it to "1" in a
# spawned delegate's environment.  This only protects the approved wrappers
# in this module; it cannot stop a delegate from invoking some other
# installed CLI directly.
DELEGATION_DEPTH_ENV = "AGENT_DELEGATION_DEPTH"

# Provenance-only identifier for whichever agent/process is acting as the
# primary owner (e.g. "codex", "claude-code", "manual"). Recorded for audit
# purposes; it is never used to make a safety decision.
DELEGATION_CALLER_ENV = "AGENT_DELEGATION_CALLER"
DEFAULT_CALLER = "unknown"


@dataclass(frozen=True)
class DelegateSpec:
    """Pinned configuration for one operational consultation delegate."""

    name: str
    executable: str
    model: str
    effort: str | None
    mode: str = "consult"


DELEGATES: dict[str, DelegateSpec] = {
    "flash": DelegateSpec("flash", "agy", "gemini-3.7-flash-medium", "medium"),
    "haiku": DelegateSpec("haiku", "claude", "claude-haiku-4-5-20251001", "medium"),
    "sonnet": DelegateSpec("sonnet", "claude", "claude-sonnet-5", "medium"),
}


def _read_only_instruction(task: str, workspace: Path) -> str:
    return f"""You are a read-only consultation delegate.

Assigned workspace: {workspace}
Allowed scope: inspect only files inside that workspace. Do not read parent
directories, home directories, credentials, benchmark private material, or
other workspaces. Do not edit, create, delete, rename, or execute files. Do
not use network tools. Do not invoke, request, or delegate to another agent or
CLI. Return a concise evidence-backed consultation in your final response,
including relevant file paths and uncertainties.

Task:
{task}
"""


def build_argv(spec: DelegateSpec, workspace: Path, task: str) -> list[str]:
    """Build a documented, non-bypass read-only consultation argv list.

    The final prompt remains one argv item.  The caller uses ``workspace`` as
    process CWD; Codex additionally receives a read-only sandbox and is kept
    available here for a future *non-recursive* direct consultation pathway,
    though no Codex wrapper is installed by this foundation.
    """
    prompt = _read_only_instruction(task, workspace)
    if spec.name in {"haiku", "sonnet"}:
        return [
            "claude", "--output-format", "json", "--no-session-persistence",
            "--safe-mode", "--permission-mode", "plan",
            "--tools", ",".join(READ_ONLY_CLAUDE_TOOLS),
            "--allowedTools", ",".join(READ_ONLY_CLAUDE_TOOLS),
            "--model", spec.model, "--effort", spec.effort or "medium",
            "-p", prompt,
        ]
    if spec.name == "flash":
        return [
            "agy", "--output-format", "json", "--mode", "plan", "--sandbox",
            "--model", spec.model, "--effort", spec.effort or "medium",
            "-p", prompt,
        ]
    if spec.name == "codex":
        return [
            "codex", "exec", "--ephemeral", "--skip-git-repo-check",
            "--sandbox", "read-only", "--cd", str(workspace), "--json",
            "--model", spec.model, "--config", f'model_reasoning_effort="{spec.effort or "medium"}"',
            prompt,
        ]
    raise ValueError(f"unsupported delegate: {spec.name}")


def default_log_root() -> Path:
    """The XDG state directory's ``delegate_runs``, independent of ``__file__``.

    This resolves the same way whether ``delegation`` is imported from a
    source checkout or an installed site-packages copy, and never writes
    into the source repository or an installed package directory. Pass
    ``log_root=`` to override, e.g. for tests or a dev-time preference.
    """
    return _xdg_log_root()


def _check_recursion_guard() -> None:
    """Reject an invocation already running inside a delegated context.

    Only the inherited ``AGENT_DELEGATION_DEPTH`` environment marker is
    consulted; a caller-supplied argument could not be trusted for this.
    Any value >= 1, including a malformed one, is rejected fail-closed.
    """
    raw = os.environ.get(DELEGATION_DEPTH_ENV)
    if raw is None:
        return
    try:
        depth = int(raw)
    except ValueError as exc:
        raise ValueError(
            f"recursive delegation rejected: malformed {DELEGATION_DEPTH_ENV}={raw!r}"
        ) from exc
    if depth >= 1:
        raise ValueError(
            f"recursive delegation rejected: {DELEGATION_DEPTH_ENV}={depth} indicates this "
            "process is already running inside a delegated context; a delegate must never "
            "invoke another delegate"
        )


def _resolve_caller(caller: str | None) -> str:
    return caller or os.environ.get(DELEGATION_CALLER_ENV) or DEFAULT_CALLER


def _check_self_provider_guard(delegate_name: str, primary: str | None) -> str | None:
    """Reject a delegate whose provider matches the declared primary's own.

    Distinct from :func:`_check_recursion_guard`: the recursion guard stops
    ``delegate -> wrapper -> another delegate`` using an inherited, hard-to-
    forge environment marker. This guard stops ``primary -> external call to
    its own provider`` using a caller-declared ``primary`` value -- it is a
    routing/policy nudge, not a security boundary, and it is only enforced
    when a primary is actually declared (fail-open on an absent value, since
    it cannot otherwise be verified). Returns the normalized primary (or
    ``None`` if undeclared) for the caller to record.
    """
    normalized = routing.normalize_primary(primary)
    if normalized is None or normalized == "manual":
        return normalized
    if routing.ROUTE_PROVIDER.get(delegate_name) == normalized:
        raise ValueError(
            f"same-provider external delegation disabled: primary={normalized!r} cannot "
            f"externally invoke its own provider via ask-{delegate_name}; use a native "
            "agent/subagent capability instead"
        )
    return normalized


def _validate_scope(workspace: Path) -> Path:
    resolved = workspace.expanduser().resolve()
    marker = resolved / ".delegation-scope.json"
    if not resolved.is_dir():
        raise ValueError(f"workspace does not exist or is not a directory: {resolved}")
    if any(path.is_symlink() for path in resolved.rglob("*")):
        raise ValueError("read-only consultation workspace must not contain symlinks")
    if not marker.is_file():
        raise ValueError(
            f"read-only consultation requires scope marker: {marker}; "
            "create it only in a dedicated, least-privilege workspace"
        )
    try:
        scope = json.loads(marker.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid scope marker JSON: {marker}") from exc
    if not isinstance(scope, dict) or scope.get("mode") != "read-only":
        raise ValueError("scope marker must contain {\"mode\": \"read-only\"}")
    return resolved


def _record_path(log_root: Path, delegate: str) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return log_root / f"{timestamp}-{delegate}-{uuid.uuid4().hex[:10]}"


def run_consultation(
    delegate_name: str,
    workspace: Path,
    task: str,
    *,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    log_root: Path | None = None,
    caller: str | None = None,
    primary: str | None = None,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[int, Path]:
    """Run exactly one read-only delegate and retain an auditable local record.

    The environment is passed through only to support the user's authenticated
    CLI sessions; it is never serialized.  The spawned delegate's environment
    always has ``AGENT_DELEGATION_DEPTH`` set to ``"1"`` so an approved
    wrapper cannot be recursively invoked from inside it.  Logs are outside
    ``workspace`` so the administrator's evidence collection does not modify
    the consulted project.  A timeout is represented as exit code 124.

    ``primary``, if given, is checked by the self-provider guard (see
    :func:`_check_self_provider_guard`) and recorded for audit; it is a
    distinct mechanism from the recursion-depth guard above.
    """
    _check_recursion_guard()
    if delegate_name not in DELEGATES:
        raise ValueError(f"unknown delegate: {delegate_name}")
    if timeout_seconds <= 0:
        raise ValueError("timeout must be positive")
    normalized_primary = _check_self_provider_guard(delegate_name, primary)
    resolved_caller = _resolve_caller(caller)
    workspace = _validate_scope(workspace)
    spec = DELEGATES[delegate_name]
    executable = shutil.which(spec.executable)
    if not executable:
        raise RuntimeError(f"delegate executable is unavailable: {spec.executable}")
    argv = build_argv(spec, workspace, task)
    resolved_log_root = (log_root or default_log_root()).expanduser().resolve()
    if resolved_log_root == workspace or resolved_log_root.is_relative_to(workspace):
        raise ValueError("log root must be outside the consulted workspace")
    record_dir = _record_path(resolved_log_root, delegate_name)
    record_dir.mkdir(parents=True, exist_ok=False)
    prompt = argv[-1]
    (record_dir / "prompt.md").write_text(prompt)
    started_at = datetime.now(timezone.utc).isoformat()
    begun = time.monotonic()
    stdout = ""
    stderr = ""
    timed_out = False
    child_env = dict(os.environ)
    child_env[DELEGATION_DEPTH_ENV] = "1"
    try:
        completed = run(
            argv, cwd=workspace, text=True, capture_output=True, timeout=timeout_seconds,
            env=child_env,
        )
        exit_code = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        timed_out = True
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
    wall_seconds = time.monotonic() - begun
    (record_dir / "stdout.txt").write_text(stdout)
    (record_dir / "stderr.txt").write_text(stderr)
    record = {
        "delegate": spec.name,
        "mode": spec.mode,
        "caller": resolved_caller,
        "declared_primary": normalized_primary or "not-declared",
        "requested_model": spec.model,
        "requested_effort": spec.effort,
        "workspace": str(workspace),
        "started_at": started_at,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "wall_seconds": wall_seconds,
        "timeout_seconds": timeout_seconds,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "argv": argv[:-1] + ["<PROMPT>"],
        "prompt_file": "prompt.md",
        "stdout_file": "stdout.txt",
        "stderr_file": "stderr.txt",
        "permission_strategy": (
            "Claude plan mode with Read/Glob/Grep only"
            if spec.name in {"haiku", "sonnet"}
            else "Antigravity plan mode with sandbox"
        ),
        "environment_captured": False,
        "recursive_delegation_enabled": False,
        "child_delegation_depth": 1,
    }
    (record_dir / "execution.json").write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return exit_code, record_dir
