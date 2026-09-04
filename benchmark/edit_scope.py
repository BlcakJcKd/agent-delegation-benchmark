"""Deterministic, safe matching for Ekalavya relative edit-scope paths."""

from __future__ import annotations

import fnmatch
import re


_DRIVE = re.compile(r"^[A-Za-z]:")


def normalize_relative_path(value: str) -> tuple[str, ...] | None:
    """Return normalized path components, or None for unsafe paths."""
    if not isinstance(value, str) or not value or "\x00" in value:
        return None
    value = value.replace("\\", "/")
    if value.startswith("/") or _DRIVE.match(value):
        return None
    parts = tuple(part for part in value.split("/") if part not in ("", "."))
    if not parts or any(part == ".." for part in parts):
        return None
    return parts


def _match(parts: tuple[str, ...], pattern: tuple[str, ...]) -> bool:
    if not pattern:
        return not parts
    if pattern[0] == "**":
        return _match(parts, pattern[1:]) or bool(parts and _match(parts[1:], pattern))
    return bool(parts and fnmatch.fnmatchcase(parts[0], pattern[0]) and _match(parts[1:], pattern[1:]))


def matches_edit_scope(path: str, patterns: tuple[str, ...] | list[str]) -> bool:
    """Match a relative path against Ekalavya patterns.

    ``*`` and ``?`` match within one path component. ``**`` matches zero or
    more complete components, so ``inventory/**/*.py`` matches both
    ``inventory/api.py`` and arbitrarily nested Python files.
    """
    path_parts = normalize_relative_path(path)
    if path_parts is None:
        return False
    for raw_pattern in patterns:
        pattern_parts = normalize_relative_path(raw_pattern)
        if pattern_parts is not None and _match(path_parts, pattern_parts):
            return True
    return False
