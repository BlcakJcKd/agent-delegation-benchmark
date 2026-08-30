"""Interactive terminal checkbox screen for ``delegate-config`` (no subcommand).

Split deliberately in two layers:

- Pure state-transition functions (``build_rows``, ``toggle``, ``set_reason``,
  ``rows_to_config``, ``diff_summary``) operate on plain data and contain all
  the actual logic. These are unit-tested directly, without a TTY.
- The curses event loop (``run_interactive_config``, ``_loop``, ``_render``)
  drives those functions but is not itself unit-tested -- driving a real
  curses screen in a test is impractical and unnecessary; the logic it
  depends on is what matters and is covered.

Toggling a provider row never cascades to its models' own enabled
preference: a disabled provider overrides *effective* availability (computed
in ``delegation.status``) without erasing which models were individually
enabled, so re-enabling the provider later restores them automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from . import routing
from .config import load_config, save_config
from .vllm import VLLMRouteInfo, inspect_vllm_routes

PROVIDER_ORDER: tuple[str, ...] = ("gemini", "claude", "codex", "deepseek", "minimax")
PROVIDER_LABELS: dict[str, str] = {
    "gemini": "Gemini", "claude": "Claude", "codex": "Codex",
    "deepseek": "DeepSeek", "minimax": "MiniMax",
}
MODEL_LABELS: dict[str, str] = {
    "flash": "Flash", "sonnet": "Sonnet", "haiku": "Haiku", "terra": "Terra", "luna": "Luna",
    "deepseek-pro": "V4 Pro", "deepseek-flash": "V4 Flash", "minimax-m3": "M3",
}


@dataclass(frozen=True)
class Row:
    kind: str  # "provider" | "model"
    section: str  # "providers" | "models"
    name: str
    label: str
    enabled: bool
    reason: str | None
    provider: str | None  # owning provider name for a model row; None for a provider row
    details: tuple[str, ...] = ()


def build_rows(
    config: dict[str, Any],
    vllm_routes: dict[str, VLLMRouteInfo] | None = None,
) -> list[Row]:
    rows: list[Row] = []
    for provider in PROVIDER_ORDER:
        entry = config["providers"][provider]
        rows.append(Row(
            "provider", "providers", provider, PROVIDER_LABELS[provider],
            entry["enabled"], entry.get("reason"), None,
        ))
        for model in sorted(m for m in routing.MODELS if routing.ROUTE_PROVIDER[m] == provider):
            m_entry = config["models"][model]
            rows.append(Row(
                "model", "models", model, MODEL_LABELS[model],
                m_entry["enabled"], m_entry.get("reason"), provider,
            ))
    # Keep this pure by default; the interactive entry point supplies the
    # machine-local inspection explicitly.  This also keeps library callers
    # and tests independent of whichever vllm.toml happens to exist.
    routes = vllm_routes or {}
    for name in sorted(set(routes) | set(config.get("vllm", {}))):
        entry = config.get("vllm", {}).get(name, {"enabled": True})
        info = routes.get(name)
        details: tuple[str, ...]
        if info and info.provider:
            provider = info.provider
            details = (
                f"model: {provider.model}",
                "type: shared vLLM / OpenAI-compatible",
                f"shared compute: {'yes' if provider.shared_compute else 'no'}",
                f"concurrency: {provider.max_concurrency}",
                f"thinking default: {'on' if provider.thinking_default else 'off'}",
                f"output default: {provider.default_max_tokens} tokens",
                f"output cap: {provider.max_tokens_cap} tokens",
                "credential: configured reference",
            )
        elif info:
            details = (f"state: {info.error_kind or 'invalid configuration'}",)
        else:
            details = ("state: local vLLM route definition missing",)
        rows.append(Row(
            "vllm", "vllm", name, name, entry.get("enabled", True),
            entry.get("reason"), None, details,
        ))
    return rows


def toggle(rows: list[Row], index: int) -> list[Row]:
    """Flip one row's enabled state; enabling clears a stale reason."""
    row = rows[index]
    updated = replace(row, enabled=not row.enabled)
    if updated.enabled:
        updated = replace(updated, reason=None)
    return rows[:index] + [updated] + rows[index + 1:]


def set_reason(rows: list[Row], index: int, reason: str | None) -> list[Row]:
    updated = replace(rows[index], reason=(reason or None))
    return rows[:index] + [updated] + rows[index + 1:]


def rows_to_config(original: dict[str, Any], rows: list[Row]) -> dict[str, Any]:
    updated = {section: {n: dict(e) for n, e in entries.items()} for section, entries in original.items()}
    for row in rows:
        updated.setdefault(row.section, {})
        entry: dict[str, Any] = {"enabled": row.enabled}
        if row.reason:
            entry["reason"] = row.reason
        updated[row.section][row.name] = entry
    return updated


def diff_summary(original: dict[str, Any], rows: list[Row]) -> list[str]:
    lines = []
    for row in rows:
        before = original.get(row.section, {}).get(row.name, {"enabled": True})
        before_reason = before.get("reason") or None
        if before.get("enabled", True) != row.enabled or before_reason != row.reason:
            before_state = "enabled" if before.get("enabled", True) else "disabled"
            after_state = "enabled" if row.enabled else "disabled"
            reason = f' (reason: "{row.reason}")' if row.reason else ""
            lines.append(f"{row.name}: {before_state} -> {after_state}{reason}")
    return lines


def _row_height(row: Row) -> int:
    return 1 + len(row.details)


def _render(stdscr, rows: list[Row], cursor: int) -> None:
    import curses

    stdscr.erase()
    height, width = stdscr.getmaxyx()
    stdscr.addstr(0, 0, "Agent Delegation Configuration"[: max(1, width - 1)], curses.A_BOLD)
    y = 2
    available = max(1, height - 6)
    start = 0
    while start < cursor and sum(_row_height(row) for row in rows[start:cursor]) >= available:
        start += 1
    for i in range(start, len(rows)):
        row = rows[i]
        if y >= height - 6:
            break
        indent = "    " if row.kind == "model" else ""
        box = "[x]" if row.enabled else "[ ]"
        reason = f"   {row.reason}" if (row.reason and row.kind in {"provider", "vllm"}) else ""
        name = row.name if row.kind == "provider" else row.provider
        if row.kind == "vllm":
            name = row.label
        # PAYG providers/routes are visually tagged so they're never
        # mistaken for the existing subscription/quota-based ones.
        badge = "   PAYG · experimental" if routing.PROVIDER_BILLING.get(name) == "payg" else ""
        line = f"{indent}{box} {row.label}{badge}{reason}"
        attr = curses.A_REVERSE if i == cursor else curses.A_NORMAL
        try:
            stdscr.addstr(y, 0, line[: max(1, width - 1)], attr)
        except Exception:
            pass
        y += 1
        if row.details:
            for detail in row.details:
                if y >= height - 6:
                    break
                try:
                    stdscr.addstr(y, 4, detail[: max(1, width - 5)], curses.A_DIM)
                except Exception:
                    pass
                y += 1
    footer_y = max(0, height - 3)
    footer = "↑/↓ navigate  Space toggle  r reason  Enter/s save  q cancel"
    try:
        stdscr.addstr(footer_y, 0, footer[: max(1, width - 1)])
    except Exception:
        pass
    stdscr.refresh()


def _prompt_reason(stdscr) -> str | None:
    import curses

    height, width = stdscr.getmaxyx()
    y = max(0, height - 2)
    prompt = "Reason (blank to clear), Enter to confirm: "
    curses.echo()
    try:
        stdscr.addstr(y, 0, prompt[: max(1, width - 1)])
        stdscr.clrtoeol()
        stdscr.refresh()
        col = min(len(prompt), max(0, width - 2))
        raw = stdscr.getstr(y, col).decode("utf-8", errors="replace")
    except Exception:
        raw = ""
    finally:
        curses.noecho()
    return raw.strip() or None


def _loop(stdscr, rows: list[Row]) -> list[Row] | None:
    import curses

    curses.curs_set(0)
    cursor = 0
    while True:
        _render(stdscr, rows, cursor)
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            cursor = max(0, cursor - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            cursor = min(len(rows) - 1, cursor + 1)
        elif key == ord(" "):
            rows = toggle(rows, cursor)
        elif key == ord("r"):
            reason = _prompt_reason(stdscr)
            rows = set_reason(rows, cursor, reason)
        elif key in (curses.KEY_ENTER, 10, 13, ord("s")):
            return rows
        elif key == ord("q"):
            return None


def run_interactive_config() -> int:
    import curses

    config = load_config()
    rows = build_rows(config, inspect_vllm_routes())
    result = curses.wrapper(_loop, rows)
    if result is None:
        print("delegate-config: cancelled, no changes made")
        return 0
    changes = diff_summary(config, result)
    if not changes:
        print("delegate-config: no changes made")
        return 0
    save_config(rows_to_config(config, result))
    print("delegate-config: saved")
    for line in changes:
        print(f"  {line}")
    return 0
