from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import signal
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapters import ADAPTERS, Adapter, configured_adapters
from .command_agents import CommandAgentConfigurationError, load_command_agents
from .evaluate import evaluate
from .freeze import verify_lock
from .preflight import display_preflight, parse_models, run_preflight
from .tasks import TASKS, repository_root, task_by_id
from .tiers import TIERS, Tier, tier_by_id
from .v2.telemetry import parse_trace


DISPLAY_NAMES = {"codex": "Codex", "claude": "Claude", "agy": "Antigravity"}
CODEX_REASONING_EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
CLAUDE_REASONING_EFFORTS = ("low", "medium", "high", "xhigh", "max")


def _write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def availability(adapters: dict[str, Adapter] = ADAPTERS) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, adapter in adapters.items():
        ok, detail = adapter.availability()
        result[name] = detail if ok else f"UNAVAILABLE: {detail}"
    return result


def prepare(
    run_label: str,
    task_ids: list[str],
    agents: list[str],
    root: Path | None = None,
    tier: Tier | None = None,
    requested_configuration: dict[str, object] | None = None,
    contestant_execution_order: dict[str, list[str]] | None = None,
    task_agents: dict[str, list[str]] | None = None,
    run_context: dict[str, object] | None = None,
) -> Path:
    root = root or repository_root()
    problems = verify_lock(root)
    if problems:
        raise RuntimeError("fixture lock verification failed:\n" + "\n".join(problems))
    run_root = root / "runs" / run_label
    if run_root.exists():
        raise FileExistsError(f"run label already exists: {run_label}")
    for task_id in task_ids:
        task_by_id(task_id)
        fixture = root / "fixtures" / task_id
        prompt = (root / "tasks/prompts" / f"{task_id}.md").read_text()
        for agent in (task_agents or {}).get(task_id, agents):
            workspace = run_root / task_id / agent / "workspace"
            shutil.copytree(fixture, workspace)
            (workspace / "TASK.md").write_text(prompt)
            (workspace / ".benchmark-agent.txt").write_text("Work only in this workspace. Do not access parent directories.\n")
            meta = workspace.parent / "meta"
            meta.mkdir()
            (meta / "prompt.md").write_text(prompt)
    record: dict[str, object] = {
        "run_label": run_label, "tasks": task_ids, "agents": agents,
        "prepared_at": datetime.now(timezone.utc).isoformat(), "fixture_lock": "fixtures.lock.json",
        "benchmark_tier": tier.id if tier else None,
        "tier_configuration": tier.metadata() if tier else None,
        # A tier is the canonical configuration source, not a requirement that
        # every tier member be launched in this particular invocation.  This is
        # needed for controlled resume runs after a single contestant failure.
        "tier_agents_available": sorted(tier.models) if tier else None,
        "agents_requested": agents if tier else None,
        "tier_execution_scope": (
            "complete"
            if tier
            and set(agents) == set(tier.models)
            and all(set((task_agents or {}).get(task_id, agents)) == set(tier.models) for task_id in task_ids)
            else "partial"
        ) if tier else None,
        "requested_configuration": requested_configuration,
        "task_agents": task_agents,
        "contestant_execution_order": contestant_execution_order,
        "crossover": (run_context or {}).get("crossover"),
        "source_tier_reference": (run_context or {}).get("source_tier_reference"),
    }
    _write_json(run_root / "run.json", record)
    return run_root


def _snapshot(workspace: Path) -> dict[str, str]:
    return {
        path.relative_to(workspace).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(workspace.rglob("*")) if path.is_file()
    }


def _json_outputs(stdout: str) -> list[object]:
    try:
        return [json.loads(stdout)]
    except json.JSONDecodeError:
        pass
    values: list[object] = []
    for line in stdout.splitlines():
        try:
            values.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return values


def _interesting(value: object) -> object:
    """Keep only CLI-emitted model/usage-shaped fields; never equate their metrics."""
    if isinstance(value, list):
        items = [_interesting(item) for item in value]
        return [item for item in items if item not in ({}, [])]
    if not isinstance(value, dict):
        return value
    selected: dict[str, object] = {}
    for key, child in value.items():
        lower = key.lower()
        if any(token in lower for token in ("model", "usage", "token", "cost", "duration")):
            selected[key] = child
        elif isinstance(child, (dict, list)):
            nested = _interesting(child)
            if nested not in ({}, []):
                selected[key] = nested
    return selected


def _observed_cli_report(stdout: str) -> dict[str, object]:
    values = _json_outputs(stdout)
    if not values:
        return {"format": "unparsed"}
    report = _interesting(values[0] if len(values) == 1 else values)
    return {"format": "json" if len(values) == 1 else "jsonl", "reported_fields": report}


def _observed_model(stdout: str) -> str | None:
    """Extract a directly emitted resolved model name when a CLI exposes one."""
    def visit(value: object) -> str | None:
        if isinstance(value, dict):
            for key in ("model", "model_name", "modelName", "resolved_model", "resolvedModel"):
                candidate = value.get(key)
                if isinstance(candidate, str):
                    return candidate
            for child in value.values():
                found = visit(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = visit(child)
                if found:
                    return found
        return None
    for value in _json_outputs(stdout):
        found = visit(value)
        if found:
            return found
    return None


def _permission_denials(stdout: str) -> list[dict[str, object]]:
    denials: list[dict[str, object]] = []

    def visit(value: object) -> None:
        if isinstance(value, dict):
            reported = value.get("permission_denials")
            if isinstance(reported, list):
                denials.extend(item for item in reported if isinstance(item, dict))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for value in _json_outputs(stdout):
        visit(value)
    return denials


def _blocking_permission_denial(
    task_id: str, denials: list[dict[str, object]], required_output_missing: bool,
) -> bool:
    """Only classify denials that blocked delivery or required local verification.

    A denied optional action (for example a status command) remains recorded but
    must not convert a completed deliverable into a harness failure. Writes and
    edits are necessary for write tasks; the three configured Python tasks also
    require local Python/pytest execution to complete their intended workflow.
    """
    if not denials:
        return False
    if required_output_missing:
        return True
    for denial in denials:
        tool_name = denial.get("tool_name")
        if tool_name in {"Write", "Edit"}:
            return True
        tool_input = denial.get("tool_input")
        command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
        if tool_name == "Bash" and task_id in {"research_python", "diagnostic_plot", "debug_package"}:
            if isinstance(command, str) and command.lstrip().startswith(("python ", "python3 ", "pytest ")):
                return True
    return False


def _requested_configuration(
    adapter: Adapter, agent: str, tier: Tier | None, task_id: str | None = None,
) -> dict[str, object]:
    configuration = adapter.describe(task_id)
    if tier:
        configuration["tier_requested_reasoning_effort"] = tier.metadata()["requested_reasoning_effort"][agent]
    return configuration


def _required_output_exists(task_id: str, workspace: Path) -> bool:
    expected = workspace / task_by_id(task_id).output_path
    return expected.exists()


def randomized_execution_order(
    task_ids: list[str], agents: list[str], task_agents: dict[str, list[str]] | None = None,
) -> dict[str, list[str]]:
    """Choose and retain an independent, non-fixed contestant order per task."""
    randomizer = random.SystemRandom()
    orders: dict[str, list[str]] = {}
    previous: list[str] | None = None
    for task_id in task_ids:
        order = list((task_agents or {}).get(task_id, agents))
        if len(order) > 1:
            while order == previous:
                randomizer.shuffle(order)
        orders[task_id] = order
        previous = order
    return orders


def _run_command_with_timeout(
    command: list[str], *, cwd: Path, env: dict[str, str], timeout: int,
) -> tuple[int | None, bool, str, str]:
    """Run one candidate and clean up its descendants if it times out.

    A plain ``subprocess.run(timeout=...)`` kills only the direct child.  A
    coding-agent CLI can leave shells, interpreters, or other tools behind,
    so POSIX candidates receive a private process session and the whole
    session is terminated on timeout.  The parent benchmark process is never
    part of that session.
    """
    popen_kwargs: dict[str, Any] = {
        "cwd": cwd,
        "text": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "env": env,
    }
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    process = subprocess.Popen(command, **popen_kwargs)
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        return process.returncode, False, stdout or "", stderr or ""
    except subprocess.TimeoutExpired as exc:
        previous_stdout = exc.stdout or ""
        previous_stderr = exc.stderr or ""
        if os.name == "posix":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        else:
            process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()
            stdout, stderr = process.communicate()
        return None, True, stdout or previous_stdout, stderr or previous_stderr


def execute(
    run_label: str,
    task_ids: list[str],
    agents: list[str],
    root: Path | None = None,
    timeout: int = 900,
    adapters: dict[str, Adapter] | None = None,
    tier: Tier | None = None,
    execution_order: dict[str, list[str]] | None = None,
    task_agents: dict[str, list[str]] | None = None,
    run_context: dict[str, object] | None = None,
) -> int:
    """Run prepared contestants. Preflight is performed by the CLI before this function."""
    root = root or repository_root()
    adapters = adapters or ADAPTERS
    execution_order = execution_order or randomized_execution_order(task_ids, agents, task_agents)
    run_root = root / "runs" / run_label
    if not run_root.exists():
        prepare(
            run_label, task_ids, agents, root, tier=tier,
            requested_configuration={name: _requested_configuration(adapters[name], name, tier) for name in agents},
            contestant_execution_order=execution_order,
            task_agents=task_agents,
            run_context=run_context,
        )
    unavailable = {name: detail for name, detail in availability(adapters).items() if name in agents and detail.startswith("UNAVAILABLE:")}
    if unavailable:
        _write_json(run_root / "unavailable.json", unavailable)
        print(json.dumps(unavailable, indent=2), file=sys.stderr)
        return 2

    hard_failures = False
    for task_id in task_ids:
        print(f"Benchmark: {task_id}")
        print(f"Run: {run_label}")
        prompt = (root / "tasks/prompts" / f"{task_id}.md").read_text()
        scores: list[tuple[str, float, float]] = []
        ordered_agents = execution_order[task_id]
        total = len(ordered_agents)
        for index, agent in enumerate(ordered_agents, start=1):
            label = DISPLAY_NAMES.get(agent, agent)
            print(f"[{index}/{total}] {label:<12} starting...", flush=True)
            workspace = run_root / task_id / agent / "workspace"
            result_dir = workspace.parent / "result"
            result_dir.mkdir(exist_ok=True)
            before = _snapshot(workspace)
            command = adapters[agent].command(workspace, prompt, result_dir, task_id=task_id)
            started = time.monotonic()
            exit_code, timed_out, stdout, stderr = _run_command_with_timeout(
                command,
                cwd=workspace,
                timeout=timeout,
                env={**os.environ, "BENCHMARK_WORKSPACE": str(workspace)},
            )
            elapsed = time.monotonic() - started
            after = _snapshot(workspace)
            changed = sorted({path for path in set(before) | set(after) if before.get(path) != after.get(path)})
            (result_dir / "stdout.txt").write_text(stdout)
            (result_dir / "stderr.txt").write_text(stderr)
            observed = _observed_cli_report(stdout)
            required_output_missing = not _required_output_exists(task_id, workspace)
            permission_denials = _permission_denials(stdout)
            interaction_blocked = _blocking_permission_denial(task_id, permission_denials, required_output_missing)
            protocol_failure = bool(stdout.strip()) and observed["format"] == "unparsed"
            failure_reasons: list[str] = []
            if timed_out:
                failure_reasons.append("timeout")
            if exit_code != 0:
                failure_reasons.append("nonzero_exit")
            if interaction_blocked:
                failure_reasons.append("interactive_permission_block")
            if required_output_missing and protocol_failure:
                failure_reasons.append("expected_structured_cli_output_was_not_received")
            # A valid CLI response with an incorrect/missing deliverable remains an evaluator
            # result, not a harness failure. Protocol and approval failures are not.
            hard_failure = bool(failure_reasons)
            record: dict[str, Any] = {
                "command": command,
                "requested_configuration": _requested_configuration(adapters[agent], agent, tier, task_id),
                "benchmark_tier": tier.id if tier else None,
                "crossover": (run_context or {}).get("crossover"),
                "source_tier_reference": (run_context or {}).get("source_tier_reference"),
                "observed_model": _observed_model(stdout),
                "wall_clock_seconds": elapsed,
                "exit_code": exit_code,
                "timed_out": timed_out,
                "files_changed": changed,
                "cli_reported_usage_hint": observed,
                "interaction_blocked": interaction_blocked,
                "permission_denials": permission_denials,
                "required_output_missing": required_output_missing,
                "harness_failure_reasons": failure_reasons,
                "execution_status": "harness_failure" if hard_failure else "completed",
                "attempt": 1,
                "retry": False,
                "fallback": None,
                "request_telemetry": [item.json() for item in parse_trace(stdout)],
            }
            _write_json(result_dir / "execution.json", record)
            assessment = evaluate(task_id, workspace, root)
            if task_by_id(task_id).mode == "read-only":
                forbidden = [path for path in changed if path != "REVIEW.md"]
                if forbidden:
                    assessment["notes"].append("read-only violation: " + ", ".join(forbidden))
                    assessment["score"] = 0.0
            _write_json(result_dir / "evaluation.json", assessment)
            _make_blind_copy(run_root, task_id, agent, workspace)
            scores.append((label, assessment["score"], assessment["maximum"]))
            state = "failed" if hard_failure else "completed"
            exit_display = "timeout" if timed_out else f"exit={exit_code}"
            print(f"[{index}/{total}] {label:<12} {state:<10} {elapsed:.1f}s   {exit_display}")
            print(f"             evaluator {assessment['score']}/{assessment['maximum']}")
            hard_failures = hard_failures or hard_failure
            if hard_failure:
                print("Controlled benchmark stopped after harness/infrastructure failure.", file=sys.stderr)
                print(f"Results: {run_root}")
                return 1
        print("Evaluation:")
        for label, score, maximum in scores:
            print(f"  {label:<12} {score}/{maximum}")
    print(f"Results: {run_root}")
    return 1 if hard_failures else 0


def _make_blind_copy(run_root: Path, task_id: str, agent: str, workspace: Path) -> None:
    source = workspace / task_by_id(task_id).output_path
    if source.is_dir() or not source.exists():
        return
    blind_id = hashlib.sha256(f"{run_root.name}:{task_id}:{agent}".encode()).hexdigest()[:12]
    target = run_root / "blind" / task_id / f"submission-{blind_id}{source.suffix or '.txt'}"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    mapping_path = run_root / "blind_map.json"
    mapping = json.loads(mapping_path.read_text()) if mapping_path.exists() else {}
    mapping[str(target.relative_to(run_root))] = {"task": task_id, "agent": agent}
    _write_json(mapping_path, mapping)


def _split_csv(value: str) -> list[str]:
    return [item for item in value.split(",") if item]


def _add_common_selection_arguments(parser: argparse.ArgumentParser, include_models: bool = True) -> None:
    parser.add_argument("--agents", default="codex,claude,agy")
    parser.add_argument("--tasks", default=",".join(task.id for task in TASKS))
    parser.add_argument(
        "--task-agents",
        help="optional semicolon-separated task=agent,agent mapping for a controlled continuation",
    )
    if include_models:
        parser.add_argument("--tier", choices=tuple(TIERS), help="named matched-practical operating tier")
        parser.add_argument("--models", help="explicit comma-separated agent=model pairs")
        parser.add_argument(
            "--codex-reasoning-effort", choices=CODEX_REASONING_EFFORTS,
            help="explicit Codex reasoning effort for a custom (non-tier) run",
        )
        parser.add_argument(
            "--claude-reasoning-effort", choices=CLAUDE_REASONING_EFFORTS,
            help="explicit Claude effort for a custom (non-tier) run",
        )
        parser.add_argument("--crossover", help="explicit crossover study identifier")
        parser.add_argument(
            "--source-tier-reference", choices=tuple(TIERS),
            help="existing tier whose frozen task evidence is being crossed over",
        )
    parser.add_argument(
        "--command-agent-config", type=Path,
        help="optional machine-local TOML mapping for generic command agents "
             "(default: XDG config agent-delegation/benchmark.toml)",
    )


def _selection(
    args: argparse.Namespace, parser: argparse.ArgumentParser,
    available_adapters: dict[str, Adapter] = ADAPTERS,
) -> tuple[list[str], list[str]]:
    agents, task_ids = _split_csv(args.agents), _split_csv(args.tasks)
    if not agents:
        parser.error("at least one agent must be selected")
    if len(set(agents)) != len(agents):
        parser.error("agents must not contain duplicates")
    if not task_ids:
        parser.error("at least one task must be selected")
    bad_agents = sorted(set(agents) - set(available_adapters))
    if bad_agents:
        parser.error("unknown agents: " + ", ".join(bad_agents))
    for task_id in task_ids:
        try:
            task_by_id(task_id)
        except KeyError:
            parser.error(f"unknown task: {task_id}")
    return agents, task_ids


def _parse_task_agents(
    value: str | None, task_ids: list[str], agents: list[str], parser: argparse.ArgumentParser,
) -> dict[str, list[str]] | None:
    """Parse an exact per-task agent plan without silently expanding it.

    This supports a controlled continuation after a previously valid subset has
    already been collected.  Every selected task must be listed once and every
    listed agent must also appear in --agents, so an invocation cannot quietly
    run an unintended contestant.
    """
    if value is None:
        return None
    result: dict[str, list[str]] = {}
    for item in value.split(";"):
        if "=" not in item:
            parser.error(f"invalid task-agent mapping: {item!r}; use task=agent,agent")
        task_id, raw_agents = item.split("=", 1)
        if task_id not in task_ids or task_id in result:
            parser.error(f"invalid or duplicate task-agent mapping task: {task_id!r}")
        selected = _split_csv(raw_agents)
        if not selected:
            parser.error(f"task-agent mapping must select at least one agent: {task_id}")
        if len(set(selected)) != len(selected):
            parser.error(f"task-agent mapping contains duplicate agents: {task_id}")
        unknown = sorted(set(selected) - set(agents))
        if unknown:
            parser.error(f"task-agent mapping selects agents not in --agents: {', '.join(unknown)}")
        result[task_id] = selected
    missing = [task_id for task_id in task_ids if task_id not in result]
    if missing:
        parser.error("task-agent mapping missing selected tasks: " + ", ".join(missing))
    return result


def _tier_or_custom_adapters(
    args: argparse.Namespace, agents: list[str], parser: argparse.ArgumentParser,
    command_agents: dict[str, Adapter] | None = None,
) -> tuple[dict[str, Adapter], list[str], Tier | None]:
    command_agents = command_agents or {}
    if args.tier:
        if args.models or args.codex_reasoning_effort or args.claude_reasoning_effort:
            parser.error("--tier supplies fixed models/efforts; do not combine it with --models or effort overrides")
        tier = tier_by_id(args.tier)
        outside_tier = sorted(set(agents) - set(tier.models))
        if outside_tier:
            parser.error(
                f"agents not defined by tier {tier.id}: " + ", ".join(outside_tier)
            )
        return configured_adapters(
            tier.models,
            codex_reasoning_effort=tier.codex_reasoning_effort,
            claude_reasoning_effort=tier.claude_reasoning_effort,
        ), [], tier
    builtin_agents = [agent for agent in agents if agent in ADAPTERS]
    if builtin_agents:
        models, model_errors = parse_models(args.models, builtin_agents)
    else:
        models, model_errors = {}, []
    unknown_model_agents = sorted(set(models) - set(agents))
    model_errors.extend(f"model supplied for unselected agent: {agent}" for agent in unknown_model_agents)
    adapters = configured_adapters(
        models,
        codex_reasoning_effort=args.codex_reasoning_effort,
        claude_reasoning_effort=args.claude_reasoning_effort,
    )
    adapters.update({name: command_agents[name] for name in agents if name in command_agents})
    return adapters, model_errors, None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Frozen-fixture CLI agent benchmark runner")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="verify frozen fixtures and list CLI availability")
    list_parser = sub.add_parser("list", help="list task ids")
    list_parser.add_argument("--verbose", action="store_true")
    preflight = sub.add_parser("preflight", help="no-model adapter and environment validation")
    _add_common_selection_arguments(preflight)
    run = sub.add_parser("run", help="preflight, prepare, and execute a comparison")
    run.add_argument("--run-label", required=True)
    run.add_argument("--timeout", type=int, default=900)
    _add_common_selection_arguments(run)
    args = parser.parse_args(argv)
    if args.command == "check":
        problems = verify_lock()
        print(json.dumps({"fixtures": "OK" if not problems else problems, "cli": availability()}, indent=2))
        return 0 if not problems else 1
    if args.command == "list":
        for task in TASKS:
            print(f"{task.id}\t{task.title}" if args.verbose else task.id)
        return 0
    try:
        command_agents = load_command_agents(getattr(args, "command_agent_config", None))
    except CommandAgentConfigurationError as exc:
        parser.error(str(exc))
    collisions = sorted(set(command_agents) & set(ADAPTERS))
    if collisions:
        parser.error("command-agent names collide with built-in agents: " + ", ".join(collisions))
    available_adapters = {**ADAPTERS, **command_agents}
    agents, task_ids = _selection(args, parser, available_adapters)
    task_agents = _parse_task_agents(args.task_agents, task_ids, agents, parser)
    if bool(args.crossover) != bool(args.source_tier_reference):
        parser.error("--crossover and --source-tier-reference must be supplied together")
    adapters, model_errors, tier = _tier_or_custom_adapters(args, agents, parser, command_agents)
    selected_adapters = {agent: adapters[agent] for agent in agents}
    report = run_preflight(repository_root(), task_ids, selected_adapters, model_errors, task_agents)
    report["benchmark_tier"] = tier.metadata() if tier else None
    report["crossover"] = args.crossover
    report["source_tier_reference"] = args.source_tier_reference
    display_preflight(report)
    if args.command == "preflight":
        return 0 if report["ok"] else 2
    if not report["ok"]:
        print("Benchmark refused: preflight failed; no contestant was started.", file=sys.stderr)
        return 2
    try:
        order = randomized_execution_order(task_ids, agents, task_agents)
        return execute(
            args.run_label, task_ids, agents, timeout=args.timeout, adapters=selected_adapters,
            tier=tier, execution_order=order, task_agents=task_agents,
            run_context={
                "crossover": args.crossover,
                "source_tier_reference": args.source_tier_reference,
            },
        )
    except (RuntimeError, FileExistsError, KeyError) as exc:
        print(f"benchmark error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
