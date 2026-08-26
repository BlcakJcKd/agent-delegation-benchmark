# Delegate configuration

How `delegate-config` and `delegate-status` work: the config schema, who
owns it, the non-interactive and interactive interfaces, and what quota
information is actually available today.

## What this config is, and isn't

`$XDG_CONFIG_HOME/agent-delegation/config.toml` (falling back to
`~/.config/agent-delegation/config.toml`) describes **availability policy**:
which providers and routes are eligible in principle. It contains no
credentials, tokens, or provider secrets — the schema rejects any field
other than `enabled` and `reason`, and `load_config`/`parse_config` raise on
an unknown provider/model name or unsupported field.

It also cannot redefine what a route resolves to. `flash` still means the
pinned `gemini-3.7-flash-medium` from `delegation.core.DELEGATES` no matter
what the config says — the config only controls whether that pinned route is
currently eligible, never what it points at.

## Schema

```toml
[providers.codex]
enabled = true

[providers.claude]
enabled = true

[providers.gemini]
enabled = true

[models.terra]
enabled = true

[models.luna]
enabled = true

[models.sonnet]
enabled = true

[models.haiku]
enabled = true

[models.flash]
enabled = false
reason = "weekly quota low"
```

Every provider (`codex`, `claude`, `gemini`) and every model/route (`terra`,
`luna`, `sonnet`, `haiku`, `flash`) supports `enabled` (required) and an
optional `reason` string. A fresh install has everything enabled — meaning
"eligible in principle," not "always externally invokable"; effective
routing still depends on the declared primary, whether the route's wrapper
executable is on PATH, and the same-provider native-agent rule (see
[CLAUDE_CODE_ORCHESTRATION.md](CLAUDE_CODE_ORCHESTRATION.md)). Terra/Luna
pin `gpt-5.6-terra`/`gpt-5.6-luna` through the normal Codex subscription
authentication path; they are external routes for non-Codex primaries and
`native-only` for a Codex primary. Sonnet/Haiku have the reciprocal Claude
native-only behavior.

**Provider disable overrides individual model enable.** Disabling `codex`
makes `terra` and `luna` unavailable even though their own `enabled` stays
`true` — and re-enabling `codex` later restores both without touching either
model entry. This is deliberate: it lets you record "Codex is out for now"
once, and have it self-heal when you flip the provider back, rather than
re-enabling every model under it by hand.

## Ownership: this is user-owned state

An AI primary agent may read, inspect, and respect this config, and should
report what it sees. It must **not** permanently change it just because it
judges quota to be low or another model preferable — persistent mutation
requires either an explicit user instruction or the human directly running
`delegate-config`. A task-scoped instruction like "don't use Codex for this
task" is a session constraint layered on top of this config, not a reason to
edit the file.

## Non-interactive commands (the stable API)

```bash
delegate-config list [--json]
delegate-config enable <route>
delegate-config disable <route> [--reason "..."]
delegate-config enable-provider <provider>
delegate-config disable-provider <provider> [--reason "..."]
```

- `list` is read-only; it never creates the config file.
- Any `enable`/`disable`/`enable-provider`/`disable-provider` call creates
  the config (with everything else defaulted to enabled) if it doesn't
  exist yet, and writes atomically (temp file + rename) — a crash mid-write
  can't corrupt the file.
- Unknown route/provider names are rejected by argument validation before
  anything is read or written.
- Enabling a route always clears its `reason` (a reason describes why
  something is disabled; carrying a stale one forward is confusing).
  Disabling without `--reason` leaves any existing reason untouched, so
  re-disabling an already-disabled route doesn't erase the last one
  recorded.
- Every command prints what changed (`flash: enabled -> disabled (reason:
  "...")`) or that nothing did (`already disabled, no change`); pass
  `--json` for a machine-readable version of the same before/after.

AI agents and scripts should use these, not the TUI below.

## Interactive TUI (the human interface)

Running `delegate-config` with no subcommand from an interactive terminal
opens a checkbox screen: providers and their models grouped underneath,
`Space` to toggle, `r` to edit/clear a reason, `Enter`/`s` to save, `q` to
cancel without writing anything. Both interfaces read and write the exact
same config file — there is no separate state.

Run without a TTY (e.g. from a script or a non-interactive agent), it prints
the non-interactive command list and exits nonzero instead of trying to
launch a screen.

## Quota is user-managed, not auto-detected

`delegate-status` always reports quota as `user-managed / unknown`, never a
percentage. As of this writing, none of the three installed CLIs this
project wraps expose a documented, machine-readable, zero-model-call quota
or usage-remaining query:

- **Codex** (`codex --help`, `codex doctor --help`): no quota/usage flag.
  `codex doctor` reports installation/config/auth/runtime health, not quota,
  and isn't a quota interface.
- **Claude Code** (`claude --help`): no quota/usage flag in the documented
  CLI surface.
- **Antigravity** (`agy --help`, `agy models`): no quota/usage flag; `models`
  lists available models, not remaining usage.

Given that, this version deliberately does not attempt to auto-disable
anything by threshold, scrape a web UI, read browser cookies, reverse-engineer
a private API, parse an undocumented credential file, infer quota from token
counts, or spend a model call just to discover remaining quota. If a future
CLI version adds a documented, safe, zero-model-call status query,
`delegate-status` could display it as advisory information — but automatic
routing should still not depend on it without a separate, deliberate change.
