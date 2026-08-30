"""CLI for delegate-config: mutate the user-owned delegation availability config.

Two interfaces over the same XDG config.toml file:

- Non-interactive subcommands (``list``, ``enable``, ``disable``,
  ``enable-provider``, ``disable-provider``) -- the stable API for scripts
  and AI agents. Prefer these; do not try to automate the TUI.
- An interactive terminal checkbox screen, launched when ``delegate-config``
  runs with no subcommand in a TTY -- the primary interface for a human.

No model calls anywhere in this module. All writes go through
``delegation.config.save_config``, which is atomic.

This config is USER-OWNED persistent state: an AI primary agent may read and
respect it, but should not call the mutating functions here on its own
judgement (e.g. "quota looks low"). Persistent mutation belongs to an
explicit user instruction or the human running this command directly.
"""

from __future__ import annotations

import argparse
import json as jsonlib
import sys
from typing import Any

from . import routing
from .config import load_config, save_config, set_enabled
from .vllm import inspect_vllm_routes

_SECTION_FOR = {**{m: "models" for m in routing.MODELS}, **{p: "providers" for p in routing.PROVIDERS}}


def _route_section(route: str) -> str:
    if route in _SECTION_FOR:
        return _SECTION_FOR[route]
    if route in load_config().get("vllm", {}):
        return "vllm"
    raise ValueError(f"unknown delegation route: {route!r}")


def _describe_change(name: str, before: dict[str, Any], after: dict[str, Any]) -> str:
    if before == after:
        state = "enabled" if after["enabled"] else "disabled"
        reason = f' (reason: "{after["reason"]}")' if after.get("reason") else ""
        return f"{name}: already {state}, no change{reason}"
    before_state = "enabled" if before["enabled"] else "disabled"
    after_state = "enabled" if after["enabled"] else "disabled"
    reason = f' (reason: "{after["reason"]}")' if after.get("reason") else ""
    return f"{name}: {before_state} -> {after_state}{reason}"


def _apply(name: str, section: str, enabled: bool, reason: str | None, as_json: bool) -> int:
    config = load_config()
    before = dict(config[section][name])
    updated = set_enabled(config, section, name, enabled, reason=reason)
    after = dict(updated[section][name])
    save_config(updated)
    if as_json:
        print(jsonlib.dumps({"name": name, "section": section, "before": before, "after": after}, sort_keys=True))
    else:
        print(_describe_change(name, before, after))
    return 0


def _cmd_list(args: argparse.Namespace) -> int:
    config = load_config()
    if args.json:
        print(jsonlib.dumps(config, indent=2, sort_keys=True))
        return 0
    for section in ("providers", "models"):
        print(section.capitalize() + ":")
        for name in sorted(config[section]):
            entry = config[section][name]
            state = "enabled" if entry["enabled"] else "disabled"
            reason = f' (reason: "{entry["reason"]}")' if entry.get("reason") else ""
            print(f"  {name:<8} {state}{reason}")
    routes = inspect_vllm_routes()
    if routes or config.get("vllm"):
        print("vLLM routes:")
        for name in sorted(set(routes) | set(config.get("vllm", {}))):
            entry = config.get("vllm", {}).get(name, {"enabled": True})
            state = "enabled" if entry["enabled"] else "disabled"
            reason = f' (reason: "{entry["reason"]}")' if entry.get("reason") else ""
            print(f"  [{'x' if entry['enabled'] else ' '}] {name}: {state}{reason}")
            info = routes.get(name)
            if info and info.provider:
                provider = info.provider
                print(f"      model: {provider.model}")
                print("      type: shared vLLM / OpenAI-compatible")
                print(f"      shared compute: {'yes' if provider.shared_compute else 'no'}")
                print(f"      concurrency: {provider.max_concurrency}")
                print(f"      thinking default: {'on' if provider.thinking_default else 'off'}")
                print(f"      output default: {provider.default_max_tokens} tokens")
                print(f"      output cap: {provider.max_tokens_cap} tokens")
                print("      credential: configured reference")
            elif info:
                print(f"      state: {info.error_kind or 'invalid configuration'}")
    return 0


def _cmd_enable(args: argparse.Namespace) -> int:
    return _apply(args.route, _route_section(args.route), True, None, args.json)


def _cmd_disable(args: argparse.Namespace) -> int:
    return _apply(args.route, _route_section(args.route), False, args.reason, args.json)


def _cmd_enable_provider(args: argparse.Namespace) -> int:
    return _apply(args.provider, "providers", True, None, args.json)


def _cmd_disable_provider(args: argparse.Namespace) -> int:
    return _apply(args.provider, "providers", False, args.reason, args.json)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect and mutate user-owned delegation availability config"
    )
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="show the configured (not effective) availability")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=_cmd_list)

    route_choices = tuple(sorted(set(routing.MODELS) | set(load_config().get("vllm", {}))))
    p_enable = sub.add_parser("enable", help="enable a route (model or named vLLM route)")
    p_enable.add_argument("route", choices=route_choices)
    p_enable.add_argument("--json", action="store_true")
    p_enable.set_defaults(func=_cmd_enable)

    p_disable = sub.add_parser("disable", help="disable a route (model or named vLLM route)")
    p_disable.add_argument("route", choices=route_choices)
    p_disable.add_argument("--reason", help="human-readable reason, e.g. 'weekly quota low'")
    p_disable.add_argument("--json", action="store_true")
    p_disable.set_defaults(func=_cmd_disable)

    p_enable_provider = sub.add_parser("enable-provider", help="enable an entire provider")
    p_enable_provider.add_argument("provider", choices=tuple(routing.PROVIDERS))
    p_enable_provider.add_argument("--json", action="store_true")
    p_enable_provider.set_defaults(func=_cmd_enable_provider)

    p_disable_provider = sub.add_parser("disable-provider", help="disable an entire provider")
    p_disable_provider.add_argument("provider", choices=tuple(routing.PROVIDERS))
    p_disable_provider.add_argument("--reason", help="human-readable reason, e.g. 'weekly quota low'")
    p_disable_provider.add_argument("--json", action="store_true")
    p_disable_provider.set_defaults(func=_cmd_disable_provider)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command is None:
        if not sys.stdout.isatty():
            print(
                "delegate-config: no subcommand given and not running in a terminal.\n"
                "Use one of: list, enable <route>, disable <route> [--reason TEXT], "
                "enable-provider <provider>, disable-provider <provider> [--reason TEXT].\n"
                "Run 'delegate-config' with no arguments from an interactive terminal for "
                "the checkbox screen instead."
            )
            return 2
        from .config_tui import run_interactive_config

        return run_interactive_config()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
