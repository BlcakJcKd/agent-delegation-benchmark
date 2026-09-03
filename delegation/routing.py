"""Shared route/provider tables for Ekalavya routing and status.

A "route" is a named consultation target (terra, luna, sonnet, haiku, flash,
deepseek-pro, deepseek-flash, minimax-m3). Each route belongs to exactly one
INFERENCE PROVIDER (codex, claude, gemini, deepseek, minimax) -- this is
distinct from its TRANSPORT (see ``ROUTE_TRANSPORT``), the CLI frontend that
actually executes the call. sonnet/haiku both use the ``claude`` transport
to reach the ``claude`` provider; deepseek-pro/deepseek-flash/minimax-m3 use
the ``codex`` transport (a pinned Codex provider-profile launcher) to reach
the ``deepseek``/``minimax`` providers, which are unrelated to Codex's own
OpenAI inference. The self-provider guard and Ekalavya status always key
off the provider, never the transport/executable name -- so a Codex-hosted
primary calling a DeepSeek or MiniMax route is a distinct, allowed provider,
while a real OpenAI-Codex-to-Codex or Claude-to-Claude call is rejected.

Only routes with an external wrapper (sonnet, haiku, flash, deepseek-pro,
deepseek-flash, minimax-m3) can ever be invoked through this package's
Terra and Luna have external wrappers for non-Codex primaries, but are
same-provider/native-only for a Codex primary. This lets Claude Code and other
non-Codex primaries consult Codex through the normal Codex subscription path
without allowing a Codex primary to recursively launch another Codex CLI.

This module does not enforce anything by itself; it is a small, dependency-
free lookup table shared by ``delegation.core`` (the self-provider guard) and
the Ekalavya status computation, so the
two can never quietly disagree about what a route or a primary alias means.
"""

from __future__ import annotations

PROVIDERS: tuple[str, ...] = ("codex", "claude", "gemini", "deepseek", "minimax")
MODELS: tuple[str, ...] = (
    "terra", "luna", "sonnet", "haiku", "flash",
    "deepseek-pro", "deepseek-flash", "minimax-m3",
)

ROUTE_PROVIDER: dict[str, str] = {
    "terra": "codex",
    "luna": "codex",
    "sonnet": "claude",
    "haiku": "claude",
    "flash": "gemini",
    "deepseek-pro": "deepseek",
    "deepseek-flash": "deepseek",
    "minimax-m3": "minimax",
}

# Executable an external wrapper invokes for a route. A same-provider primary
# is still classified as native-only by route_type(), so a Codex primary cannot
# use these Codex transport wrappers to recursively launch another Codex CLI.
#
# deepseek-pro/deepseek-flash use the `codex-deepseek` launcher and
# minimax-m3 uses `codex-minimax` -- pre-existing, independently verified
# Codex provider-profile launchers (see docs/PAYG_DELEGATES.md) that pin
# `--profile deepseek`/`--profile minimax` and retrieve their API key from
# the login keyring. They are Codex-CLI *transport*, not the `codex` route's
# own OpenAI provider.
ROUTE_EXECUTABLE: dict[str, str | None] = {
    "terra": "codex",
    "luna": "codex",
    "sonnet": "claude",
    "haiku": "claude",
    "flash": "agy",
    "deepseek-pro": "codex-deepseek",
    "deepseek-flash": "codex-deepseek",
    "minimax-m3": "codex-minimax",
}

# The CLI frontend/transport that actually executes a route's call, as
# distinct from ROUTE_PROVIDER (the inference provider). Two routes can
# share a transport while hitting different providers (deepseek-pro and
# minimax-m3 both run through the "codex" transport but reach different
# providers), and one provider can be reached through more than one
# transport in principle.
ROUTE_TRANSPORT: dict[str, str] = {
    "terra": "codex",
    "luna": "codex",
    "sonnet": "claude",
    "haiku": "claude",
    "flash": "agy",
    "deepseek-pro": "codex",
    "deepseek-flash": "codex",
    "minimax-m3": "codex",
}

# Billing class, for display only -- never used to make a routing decision.
# "quota": covered by an existing subscription/quota allowance. "payg": pay-
# as-you-go, draws down a metered balance on every call.
PROVIDER_BILLING: dict[str, str] = {
    "codex": "quota",
    "claude": "quota",
    "gemini": "quota",
    "deepseek": "payg",
    "minimax": "payg",
}
ROUTE_BILLING: dict[str, str] = {
    "terra": "quota",
    "luna": "quota",
    "sonnet": "quota",
    "haiku": "quota",
    "flash": "quota",
    "deepseek-pro": "payg",
    "deepseek-flash": "payg",
    "minimax-m3": "payg",
}

# Maturity, for display only. "experimental" routes have not been evaluated
# through this project's benchmark harness -- see docs/PAYG_DELEGATES.md.
ROUTE_MATURITY: dict[str, str] = {
    "terra": "stable",
    "luna": "stable",
    "sonnet": "stable",
    "haiku": "stable",
    "flash": "stable",
    "deepseek-pro": "experimental",
    "deepseek-flash": "experimental",
    "minimax-m3": "experimental",
}

# Provider/route names that are experimental PAYG capacity and must default
# to disabled on both a fresh install and when merging into an existing
# config that predates them (see delegation.config). Enabling them is always
# an explicit, user-owned Ekalavya configuration action.
EXPERIMENTAL_PAYG_NAMES: frozenset[str] = frozenset({
    "deepseek", "minimax", "deepseek-pro", "deepseek-flash", "minimax-m3",
})
DEFAULT_DISABLED_REASON = "experimental PAYG; benchmark pending"

# Declared --primary values accepted from a caller, normalized to a provider
# name or "manual". Deliberately explicit and small rather than inferred from
# parent-process guessing. A primary running under a DeepSeek/MiniMax
# inference route (whether fronted by `claude-deepseek`/`claude-minimax` or
# `codex-deepseek`/`codex-minimax`) normalizes to that PROVIDER, not to
# "claude" or "codex" -- its transport is irrelevant to the guard, only its
# actual inference provider is.
PRIMARY_ALIASES: dict[str, str] = {
    "claude-code": "claude",
    "claude": "claude",
    "codex": "codex",
    "codex-cli": "codex",
    "gemini": "gemini",
    "antigravity": "gemini",
    "agy": "gemini",
    "deepseek": "deepseek",
    "claude-deepseek": "deepseek",
    "codex-deepseek": "deepseek",
    "minimax": "minimax",
    "claude-minimax": "minimax",
    "codex-minimax": "minimax",
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
