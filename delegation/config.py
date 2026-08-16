"""User-owned delegation availability configuration.

Persisted as TOML at ``delegation.paths.config_path()`` (XDG config dir). This
file describes AVAILABILITY POLICY only -- which providers/routes are
eligible in principle. It must never contain credentials, tokens, or
provider secrets, and it cannot redefine what a pinned route (e.g. "flash")
resolves to at runtime; that pin lives in ``delegation.core.DELEGATES`` and
is not configurable here. See docs/DELEGATE_CONFIGURATION.md.

This is user-owned persistent state. An AI primary agent may read, inspect,
and respect it, but must not mutate it merely on its own judgement (e.g.
"quota looks low") -- persistent mutation requires either explicit user
instruction or the human directly invoking ``delegate-config``. A task-scoped
instruction such as "don't use Codex for this task" is a session constraint,
not a reason to call ``set_enabled`` here.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from .paths import config_path
from .routing import MODELS, PROVIDERS

_SECTIONS = {"providers": PROVIDERS, "models": MODELS}
_ALLOWED_ENTRY_KEYS = {"enabled", "reason"}


def default_config() -> dict[str, dict[str, dict[str, Any]]]:
    """The config used when no config file exists yet: everything enabled."""
    return {
        section: {name: {"enabled": True} for name in names}
        for section, names in _SECTIONS.items()
    }


def _validate_entry(section: str, name: str, entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ValueError(f"{section}.{name} must be a table, got {type(entry).__name__}")
    if "enabled" not in entry:
        raise ValueError(f"{section}.{name}.enabled is required")
    if not isinstance(entry["enabled"], bool):
        raise ValueError(f"{section}.{name}.enabled must be a boolean")
    if "reason" in entry and not isinstance(entry["reason"], str):
        raise ValueError(f"{section}.{name}.reason must be a string")
    extra = set(entry) - _ALLOWED_ENTRY_KEYS
    if extra:
        raise ValueError(f"{section}.{name} has unsupported field(s): {sorted(extra)}")
    result: dict[str, Any] = {"enabled": entry["enabled"]}
    if entry.get("reason"):
        result["reason"] = entry["reason"]
    return result


def parse_config(raw: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    """Validate a raw parsed-TOML dict against the known schema.

    Unknown provider/model names are rejected (no silently-ignored typos);
    a name absent from an otherwise-valid file defaults to enabled with no
    reason, matching a fresh install.
    """
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for section, names in _SECTIONS.items():
        section_raw = raw.get(section, {})
        if not isinstance(section_raw, dict):
            raise ValueError(f"[{section}] must be a table")
        unknown = set(section_raw) - set(names)
        if unknown:
            raise ValueError(f"unknown {section[:-1]}(s) in config: {sorted(unknown)}")
        result[section] = {
            name: _validate_entry(section, name, section_raw[name]) if name in section_raw
            else {"enabled": True}
            for name in names
        }
    return result


def load_config(path: Path | None = None) -> dict[str, dict[str, dict[str, Any]]]:
    """Load and validate the config, or return the default if none exists yet."""
    target = path or config_path()
    if not target.is_file():
        return default_config()
    raw = tomllib.loads(target.read_text())
    return parse_config(raw)


def _render_toml(config: dict[str, dict[str, dict[str, Any]]]) -> str:
    lines = [
        "# agent-delegation user configuration",
        "#",
        "# Describes delegation AVAILABILITY POLICY only (which providers/routes",
        "# are eligible in principle). It must never contain credentials, tokens,",
        "# or provider secrets. See docs/DELEGATE_CONFIGURATION.md.",
        "",
    ]
    for section in ("providers", "models"):
        for name in sorted(config[section]):
            entry = config[section][name]
            lines.append(f"[{section}.{name}]")
            lines.append(f"enabled = {'true' if entry['enabled'] else 'false'}")
            reason = entry.get("reason")
            if reason:
                escaped = reason.replace("\\", "\\\\").replace('"', '\\"')
                lines.append(f'reason = "{escaped}"')
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


def save_config(config: dict[str, dict[str, dict[str, Any]]], path: Path | None = None) -> Path:
    """Atomically write the config: render to a temp file, then rename in place."""
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.tmp-{os.getpid()}")
    tmp.write_text(_render_toml(config))
    tmp.replace(target)
    return target


def set_enabled(
    config: dict[str, dict[str, dict[str, Any]]],
    section: str,
    name: str,
    enabled: bool,
    reason: str | None = None,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Return a new config with one entry's enabled/reason updated.

    Enabling always clears any existing reason (a reason describes why an
    entry is disabled; carrying a stale one forward is confusing). Disabling
    sets ``reason`` when given; when not given, any existing reason on that
    entry is left untouched, so re-disabling an already-disabled route
    without a fresh reason does not erase the last recorded one.
    """
    if section not in _SECTIONS:
        raise ValueError(f"unknown config section: {section!r}")
    if name not in _SECTIONS[section]:
        raise ValueError(f"unknown {section[:-1]}: {name!r}; known: {sorted(_SECTIONS[section])}")
    updated = {sec: {n: dict(entry) for n, entry in entries.items()} for sec, entries in config.items()}
    entry = dict(updated[section][name])
    entry["enabled"] = enabled
    if enabled:
        entry.pop("reason", None)
    elif reason is not None:
        if reason:
            entry["reason"] = reason
        else:
            entry.pop("reason", None)
    updated[section][name] = entry
    return updated
