from __future__ import annotations

import json
import importlib.util
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .adapters import Adapter
from .freeze import verify_lock


HELP_REQUIREMENTS: dict[str, tuple[tuple[list[str], tuple[str, ...]], ...]] = {
    "codex": (
        (["codex", "exec", "--help"], ("--sandbox", "workspace-write", "--json", "--model", "--cd")),
    ),
    "claude": (
        (["claude", "--help"], ("--print", "--output-format", "--permission-mode", "auto", "--model", "--safe-mode")),
    ),
    "agy": (
        (["agy", "--help"], ("--print", "--output-format", "--mode", "accept-edits", "--sandbox", "--model")),
    ),
    "deepseek-pro": (
        (["codex-deepseek", "exec", "--help"], ("--sandbox", "workspace-write", "--json", "--model", "--cd")),
    ),
    "deepseek-flash": (
        (["codex-deepseek", "exec", "--help"], ("--sandbox", "workspace-write", "--json", "--model", "--cd")),
    ),
    "minimax-m3": (
        (["codex-minimax", "exec", "--help"], ("--sandbox", "workspace-write", "--json", "--model", "--cd")),
    ),
}

TASK_EXECUTABLES: dict[str, tuple[str, ...]] = {
    "research_python": ("python3",),
    "diagnostic_plot": ("python3",),
    "debug_package": ("python3",),
    "repository_review": ("python3",),
    "pandoc_pdf": ("python3", "pandoc", "pdflatex"),
    "scientific_writing": ("python3",),
}


def parse_models(value: str | None, agents: list[str]) -> tuple[dict[str, str], list[str]]:
    """Parse `agent=model` pairs without accepting implicit model defaults."""
    if not value:
        return {}, [f"model selection required for: {', '.join(agents)}"]
    models: dict[str, str] = {}
    errors: list[str] = []
    for item in value.split(","):
        if "=" not in item:
            errors.append(f"invalid model pair: {item!r}; use agent=model")
            continue
        agent, model = item.split("=", 1)
        if not agent or not model or any(char.isspace() for char in model):
            errors.append(f"invalid model pair: {item!r}")
        else:
            models[agent] = model
    missing = [agent for agent in agents if not models.get(agent)]
    if missing:
        errors.append(f"model selection required for: {', '.join(missing)}")
    return models, errors


def _capture(command: list[str]) -> tuple[int, str, str]:
    completed = subprocess.run(command, text=True, capture_output=True)
    return completed.returncode, completed.stdout, completed.stderr


def _adapter_command_problems(adapter: Adapter, task_id: str | None = None) -> list[str]:
    prompt = "<PROMPT>"
    command = adapter.command(Path("<WORKSPACE>"), prompt, Path("<RESULT_DIR>"), task_id=task_id)
    problems: list[str] = []
    if command[-1] != prompt:
        problems.append("prompt is not the final argv argument")
    if any("dangerously" in argument for argument in command):
        problems.append("dangerous permission-bypass argument is present")
    if adapter.name == "codex":
        if "--ask-for-approval" in command:
            problems.append("unsupported misplaced --ask-for-approval is present")
        if "--approve-for-me" in command:
            problems.append("--approve-for-me must not be combined with --sandbox")
        for required in ("exec", "--sandbox", "workspace-write", "--json", "--model", "--cd", "--output-last-message"):
            if required not in command:
                problems.append(f"missing Codex argument: {required}")
        if adapter.reasoning_effort and f'model_reasoning_effort="{adapter.reasoning_effort}"' not in command:
            problems.append("missing explicit Codex reasoning-effort configuration")
    if adapter.executable in {"codex-deepseek", "codex-minimax"}:
        if "--approve-for-me" in command:
            problems.append("--approve-for-me must not be combined with --sandbox")
        for required in ("exec", "--sandbox", "workspace-write", "--json", "--model", "--cd", "--output-last-message"):
            if required not in command:
                problems.append(f"missing {adapter.executable} argument: {required}")
        if 'model_reasoning_effort="high"' not in command:
            problems.append("missing explicit reasoning-effort configuration")
    if adapter.name == "claude":
        if command[command.index("--permission-mode") + 1] != "auto":
            problems.append("Claude permission mode is not auto")
        if command[-2] != "-p":
            problems.append("Claude -p must directly precede prompt")
        if getattr(adapter, "reasoning_effort", None) and "--effort" not in command:
            problems.append("missing explicit Claude reasoning-effort configuration")
        allowed = adapter.describe(task_id).get("allowed_tools", [])
        if allowed:
            if "--allowedTools" not in command:
                problems.append("missing Claude task allowlist")
            elif command[command.index("--allowedTools") + 1] != ",".join(allowed):
                problems.append("Claude task allowlist does not match task configuration")
    if adapter.name == "agy":
        if command[-2] != "-p":
            problems.append("agy -p must directly precede prompt")
        if any(flag in command[command.index("-p") + 1:] for flag in ("--output-format", "--mode", "--sandbox", "--model")):
            problems.append("agy option occurs after -p")
    return problems


def _codex_models_from_local_cache() -> list[str]:
    """Return locally cached account-visible Codex models without contacting a model."""
    cache = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "models_cache.json"
    try:
        data = json.loads(cache.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return sorted(
        item["slug"] for item in data.get("models", [])
        if isinstance(item, dict) and isinstance(item.get("slug"), str)
    )


def _claude_models_from_local_history() -> list[str]:
    """Return model IDs previously observed by this local Claude account.

    Claude Code has no documented local equivalent of `agy models`; this is an
    evidence-only check, not a claim that it guarantees present entitlement.
    """
    path = Path.home() / ".claude" / "stats-cache.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    usage = data.get("modelUsage", {})
    return sorted(key for key in usage if isinstance(key, str)) if isinstance(usage, dict) else []


def _workspace_probe(
    root: Path, task_ids: list[str], agents: list[str], task_agents: dict[str, list[str]] | None = None,
) -> list[str]:
    problems: list[str] = []
    with tempfile.TemporaryDirectory(prefix="benchmark-preflight-") as temporary:
        temporary_root = Path(temporary)
        for task_id in task_ids:
            source = root / "fixtures" / task_id
            if not source.is_dir():
                problems.append(f"fixture directory missing: {task_id}")
                continue
            for agent in (task_agents or {}).get(task_id, agents):
                workspace = temporary_root / task_id / agent / "workspace"
                shutil.copytree(source, workspace)
                if any(path.is_symlink() for path in workspace.rglob("*")):
                    problems.append(f"workspace contains a symlink: {task_id}/{agent}")
                if any("private_admin" in path.parts for path in workspace.rglob("*")):
                    problems.append(f"private material copied into {task_id}/{agent}")
    return problems


def _dependencies(task_ids: list[str]) -> dict[str, str]:
    required = sorted({program for task_id in task_ids for program in TASK_EXECUTABLES[task_id]})
    status = {program: shutil.which(program) or "MISSING" for program in required}
    if "diagnostic_plot" in task_ids:
        status["python3:matplotlib"] = "OK" if importlib.util.find_spec("matplotlib") else "MISSING"
    return status


def run_preflight(
    root: Path,
    task_ids: list[str],
    adapters: dict[str, Adapter],
    model_errors: list[str],
    task_agents: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Validate local CLI syntax and fixtures. It never submits a prompt to a model."""
    agents = list(adapters)
    checks: list[dict[str, Any]] = []
    versions: dict[str, str] = {}
    agy_models: list[str] = []
    codex_models: list[str] = []
    claude_models: list[str] = []
    for name, adapter in adapters.items():
        available, detail = adapter.availability()
        checks.append({"name": f"{name}: executable", "ok": available, "detail": detail})
        if available:
            code, stdout, stderr = _capture([adapter.executable, "--version"])
            versions[name] = (stdout or stderr).strip()
            checks.append({"name": f"{name}: version", "ok": code == 0, "detail": versions[name]})
        for help_command, required in HELP_REQUIREMENTS[name]:
            code, stdout, stderr = _capture(help_command)
            help_text = stdout + stderr
            missing = [item for item in required if item not in help_text]
            checks.append({"name": f"{name}: supported flags", "ok": code == 0 and not missing, "detail": "missing: " + ", ".join(missing) if missing else "OK"})
        for task_id in task_ids:
            if task_agents is not None and name not in task_agents[task_id]:
                continue
            problems = _adapter_command_problems(adapter, task_id)
            checks.append({
                "name": f"{name}: argv template ({task_id})",
                "ok": not problems,
                "detail": "; ".join(problems) or "OK",
                "argv": adapter.command(Path("<WORKSPACE>"), "<PROMPT>", Path("<RESULT_DIR>"), task_id=task_id),
            })
    if "codex" in adapters:
        codex_models = _codex_models_from_local_cache()
        requested = adapters["codex"].model
        checks.append({"name": "codex: locally cached account models", "ok": bool(codex_models), "detail": ", ".join(codex_models) or "cache unavailable"})
        if requested:
            checks.append({"name": "codex: requested model locally cached", "ok": requested in codex_models, "detail": requested})
    if "claude" in adapters:
        claude_models = _claude_models_from_local_history()
        requested = adapters["claude"].model
        checks.append({"name": "claude: locally observed account models", "ok": bool(claude_models), "detail": ", ".join(claude_models) or "no local model history"})
        if requested:
            observed = requested in claude_models
            checks.append({
                "name": "claude: requested model local evidence",
                "ok": True,
                "detail": requested if observed else f"{requested} not locally enumerated; Claude CLI exposes no local model-list command",
            })
    if "agy" in adapters and adapters["agy"].availability()[0]:
        code, stdout, stderr = _capture(["agy", "models"])
        agy_models = [line.split("\t", 1)[0] for line in stdout.splitlines() if "\t" in line]
        checks.append({"name": "agy: locally listed models", "ok": code == 0 and bool(agy_models), "detail": ", ".join(agy_models) or (stderr.strip() or "none")})
        requested = adapters["agy"].model
        if requested:
            checks.append({"name": "agy: requested model locally listed", "ok": requested in agy_models, "detail": requested})
    for error in model_errors:
        checks.append({"name": "model selection", "ok": False, "detail": error})
    fixture_problems = verify_lock(root)
    checks.append({"name": "fixture lock", "ok": not fixture_problems, "detail": "; ".join(fixture_problems) or "OK"})
    workspace_problems = _workspace_probe(root, task_ids, agents, task_agents)
    checks.append({"name": "workspace isolation", "ok": not workspace_problems, "detail": "; ".join(workspace_problems) or "OK"})
    dependencies = _dependencies(task_ids)
    for executable, detail in dependencies.items():
        checks.append({"name": f"dependency: {executable}", "ok": detail != "MISSING", "detail": detail})
    return {
        "ok": all(check["ok"] for check in checks),
        "versions": versions,
        "adapters": {name: adapter.describe() for name, adapter in adapters.items()},
        "agy_available_models": agy_models,
        "codex_locally_cached_models": codex_models,
        "claude_locally_observed_models": claude_models,
        "checks": checks,
    }


def display_preflight(report: dict[str, Any]) -> None:
    print("Preflight (no model invocation)")
    if report.get("benchmark_tier"):
        tier = report["benchmark_tier"]
        print(f"  tier: {tier['id']} ({tier['methodology']})")
    for name, version in report["versions"].items():
        print(f"  {name}: {version}")
    for check in report["checks"]:
        marker = "PASS" if check["ok"] else "FAIL"
        print(f"  [{marker}] {check['name']}: {check['detail']}")
        if "argv" in check:
            print("         argv=" + json.dumps(check["argv"]))
    print("Preflight: " + ("PASS" if report["ok"] else "FAIL"))
