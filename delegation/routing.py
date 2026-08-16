"""Shared route/provider tables for the self-provider guard and delegate-status.

A "route" is a named consultation target (terra, luna, sonnet, haiku, flash).
Each route belongs to exactly one provider (codex, claude, gemini). Only
routes with an external wrapper (sonnet, haiku, flash) can ever be invoked
through this package's ``ask-*`` commands; terra and luna are Codex-native
routes with no external wrapper anywhere in this codebase, and none is added
here -- see docs/DELEGATION_POLICY.md.

This module does not enforce anything by itself; it is a small, dependency-
free lookup table shared by ``delegation.core`` (the self-provider guard) and
``delegation.status`` (the read-only ``delegate-status`` computation), so the
two can never quietly disagree about what a route or a primary alias means.
"""

from __future__ import annotations

PROVIDERS: tuple[str, ...] = ("codex", "claude", "gemini")
MODELS: tuple[str, ...] = ("terra", "luna", "sonnet", "haiku", "flash")

ROUTE_PROVIDER: dict[str, str] = {
    "terra": "codex",
    "luna": "codex",
    "sonnet": "claude",
    "haiku": "claude",
    "flash": "gemini",
}

# Executable an external wrapper would invoke for a route, or None if the
# route has no external wrapper at all -- always native-only, regardless of
# the declared primary. Terra/Luna intentionally have no external wrapper:
# recursively invoking `codex exec` from a wrapper is not adopted here.
ROUTE_EXECUTABLE: dict[str, str | None] = {
    "terra": None,
    "luna": None,
    "sonnet": "claude",
    "haiku": "claude",
    "flash": "agy",
}

# Declared --primary values accepted from a caller, normalized to a provider
# name or "manual". Deliberately explicit and small rather than inferred from
# parent-process guessing.
PRIMARY_ALIASES: dict[str, str] = {
    "claude-code": "claude",
    "claude": "claude",
    "codex": "codex",
    "codex-cli": "codex",
    "gemini": "gemini",
    "antigravity": "gemini",
    "agy": "gemini",
    "manual": "manual",
    "human": "manual",
}


def normalize_primary(primary: str | None) -> str | None:
    """Normalize a declared ``--primary`` value to a provider name or "manual".

    Returns ``None`` for an absent/blank value: an undeclared primary cannot
    be verified, so routing based on it is skipped (fail-open), not assumed.
    Raises ``ValueError`` for a non-empty value that isn't a known alias.
    """
    if not primary or not primary.strip():
        return None
    key = primary.strip().lower()
    try:
        return PRIMARY_ALIASES[key]
    except KeyError:
        raise ValueError(
            f"unknown --primary value: {primary!r}; known aliases: {sorted(PRIMARY_ALIASES)}"
        ) from None


def route_type(route: str, normalized_primary: str | None) -> str:
    """Classify a route as ``"external"``, ``"same-provider"``, or ``"native-only"``.

    ``normalized_primary`` must already be normalized (see
    :func:`normalize_primary`); pass ``None`` for an undeclared primary.
    """
    if ROUTE_EXECUTABLE.get(route) is None:
        return "native-only"
    if normalized_primary and normalized_primary != "manual" and ROUTE_PROVIDER[route] == normalized_primary:
        return "same-provider"
    return "external"
