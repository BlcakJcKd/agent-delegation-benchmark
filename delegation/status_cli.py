"""CLI for delegate-status: a zero-model-call view of the effective delegation landscape.

Never invokes a delegate CLI and never queries quota; quota availability is
user-managed (see docs/DELEGATE_CONFIGURATION.md).
"""

from __future__ import annotations

import argparse
import json as jsonlib
import shutil
from importlib import metadata
from pathlib import Path
from typing import Any

from . import routing
from .config import load_config
from .paths import config_path, log_root
from .status import compute_status

DIST_NAME = "agent-delegation-benchmark"


def _runtime_version() -> str:
    try:
        return metadata.version(DIST_NAME)
    except metadata.PackageNotFoundError:
        return "dev (not installed; running from a source checkout)"


def skill_status() -> dict[str, Any]:
    source = Path.home() / ".agents" / "skills" / "delegation" / "SKILL.md"
    claude_link = Path.home() / ".claude" / "skills" / "delegation"
    return {
        "source_installed": source.is_file(),
        "source_path": str(source),
        "claude_code_discovers": claude_link.exists(),
        "claude_code_path": str(claude_link),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Zero-model-call view of the effective delegation landscape")
    parser.add_argument(
        "--primary",
        help="declared primary provider identity, e.g. claude-code, codex, gemini, manual",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def build_report(primary: str | None, which=shutil.which, config: dict | None = None) -> dict[str, Any]:
    resolved_config = config if config is not None else load_config()
    normalized_primary = routing.normalize_primary(primary)
    routes = compute_status(resolved_config, primary=primary, which=which)
    return {
        "config_path": str(config_path()),
        "state_log_path": str(log_root()),
        "runtime_version": _runtime_version(),
        "skill": skill_status(),
        "declared_primary": normalized_primary or "not-declared",
        "quota": "user-managed / unknown",
        "routes": [r.as_dict() for r in routes],
    }


def _print_human(report: dict[str, Any]) -> None:
    print(f"Config:  {report['config_path']}")
    print(f"State:   {report['state_log_path']}")
    print(f"Runtime: {report['runtime_version']}")
    skill = report["skill"]
    skill_line = "installed" if skill["source_installed"] else "not installed"
    discover_line = (
        "discovered by Claude Code" if skill["claude_code_discovers"] else "not linked for Claude Code"
    )
    print(f"Skill:   {skill_line} ({skill['source_path']}); {discover_line}")
    print(f"Primary: {report['declared_primary']}")
    print(f"Quota:   {report['quota']}")
    print()
    header = (
        f"{'Route':<15} {'Provider':<9} {'Transport':<10} {'Billing':<8} {'Maturity':<13} "
        f"{'Config':<10} {'Route type':<14} {'Effective':<18} Reason"
    )
    print(header)
    print("-" * len(header))
    for route in report["routes"]:
        config_state = "enabled" if route["configured_enabled"] else "disabled"
        reason = route["effective_reason"] or route["configured_reason"] or ""
        print(
            f"{route['route']:<15} {route['provider']:<9} {route['transport']:<10} "
            f"{route['billing']:<8} {route['maturity']:<13} {config_state:<10} "
            f"{route['route_type']:<14} {route['effective']:<18} {reason}"
        )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        report = build_report(args.primary)
    except ValueError as exc:
        print(f"delegate-status error: {exc}")
        return 2
    if args.json:
        print(jsonlib.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
