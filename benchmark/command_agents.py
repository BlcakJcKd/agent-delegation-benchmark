"""Machine-local configuration for generic benchmark coding-agent commands."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .adapters import CommandAgentAdapter


_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class CommandAgentConfigurationError(ValueError):
    """A safe, local configuration error for a command-agent mapping."""


def command_agent_config_path() -> Path:
    config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return config_root / "agent-delegation" / "benchmark.toml"


def _argv(value: Any, field: str, name: str, *, required: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or (required and not value):
        requirement = "a non-empty array" if required else "an array"
        raise CommandAgentConfigurationError(
            f"command agent {name!r} {field} must be {requirement} of strings"
        )
    if any(not isinstance(item, str) or not item for item in value):
        raise CommandAgentConfigurationError(
            f"command agent {name!r} {field} must contain only non-empty strings"
        )
    return tuple(value)


def load_command_agents(path: Path | None = None) -> dict[str, CommandAgentAdapter]:
    """Load optional local argv mappings; a missing file means no mappings."""
    target = path or command_agent_config_path()
    if not target.is_file():
        return {}
    import tomllib

    try:
        raw = tomllib.loads(target.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise CommandAgentConfigurationError(
            "command-agent configuration could not be parsed"
        ) from exc
    if set(raw) - {"command_agents"}:
        raise CommandAgentConfigurationError(
            "command-agent configuration has unsupported top-level section(s)"
        )
    entries = raw.get("command_agents", {})
    if not isinstance(entries, dict):
        raise CommandAgentConfigurationError("[command_agents] must be a table")
    result: dict[str, CommandAgentAdapter] = {}
    for name, entry in entries.items():
        if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
            raise CommandAgentConfigurationError(
                "command-agent names must be short alphanumeric names with . _ or -"
            )
        if not isinstance(entry, dict):
            raise CommandAgentConfigurationError(f"command agent {name!r} must be a table")
        unknown = set(entry) - {"command", "args"}
        if unknown:
            raise CommandAgentConfigurationError(
                f"command agent {name!r} has unsupported field(s): {sorted(unknown)}"
            )
        command = _argv(entry.get("command"), "command", name, required=True)
        args = _argv(entry.get("args", []), "args", name, required=False)
        result[name] = CommandAgentAdapter(name=name, command_argv=command, fixed_args=args)
    return result
