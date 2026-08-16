# PAYG delegates (experimental)

Two pay-as-you-go (PAYG) providers — DeepSeek and MiniMax — are wired into
the delegation system as **experimental, benchmark-pending** routes:
`deepseek-pro`, `deepseek-flash`, and `minimax-m3`. This document covers what
makes them different from the existing quota-based routes (Flash/Haiku/
Sonnet), the security assumptions they depend on, and how to enable them.

Setting up the underlying provider profiles/launchers on a machine that
doesn't have them yet is covered in
[NEW_MACHINE_SETUP.md](NEW_MACHINE_SETUP.md) (step 6) via
`scripts/setup-payg-providers.sh` and the non-secret templates in
`provider_templates/` — this document assumes that part is already done and
focuses on how the delegation layer uses it.

## Provider vs. transport

Every route has two identities that must not be conflated:

- **Provider** — the actual inference backend a call reaches (`deepseek`,
  `minimax`, `claude`, `gemini`, `codex`).
- **Transport** — the CLI frontend that executes the call.

`deepseek-pro`, `deepseek-flash`, and `minimax-m3` all use the **`codex`
transport** — they are invoked as `codex-deepseek exec ...` /
`codex-minimax exec ...`, two pre-existing, independently verified Codex
provider-profile launchers (`~/.local/bin/codex-deepseek`,
`~/.local/bin/codex-minimax`) that pin `--profile deepseek`/`--profile
minimax` — but their **provider** is DeepSeek/MiniMax, not OpenAI. Invoking
one does not touch normal OpenAI Codex inference at all: each Codex profile
(`~/.codex/deepseek.config.toml`, `~/.codex/minimax.config.toml`) declares
its own `[model_providers.*]` block with DeepSeek's/MiniMax's own
`base_url`, so the call is routed to `https://api.deepseek.com/` or
`https://api.minimax.io/v1` exclusively.

This distinction is why the self-provider guard (`delegation.core`,
`delegation.routing.ROUTE_PROVIDER`) keys off the **provider**, never the
transport or executable name. Concretely:

| Primary | `ask-deepseek-pro` / `ask-deepseek-flash` | `ask-minimax-m3` |
|---|---|---|
| Claude Code | external, allowed | external, allowed |
| Codex | external, allowed | external, allowed |
| DeepSeek (`claude-deepseek`/`codex-deepseek` as primary) | same-provider, rejected | external, allowed |
| MiniMax (`claude-minimax`/`codex-minimax` as primary) | external, allowed | same-provider, rejected |

A real OpenAI-Codex-primary calling the (unwrapped, native-only) `terra`/
`luna` routes, or a Claude-primary calling `ask-haiku`/`ask-sonnet`, remain
same-provider and rejected exactly as before — this addition only ever
widens what a *different*-provider primary may reach, and only for routes
that were not previously in the routing tables at all.

## Credential handling

This package never touches a DeepSeek or MiniMax API key. `codex-deepseek`/
`codex-minimax` retrieve it themselves from the Ubuntu login keyring via
`secret-tool lookup service ai-coding-provider provider deepseek|minimax`,
export it only into their own child `codex` process's environment, and
`unset` the shell variable holding it immediately after. Each Codex profile
additionally sets `features.shell_snapshot = false` (prevents Codex's own
shell-history snapshot mechanism from persisting it) and excludes
`DEEPSEEK_API_KEY`/`MINIMAX_API_KEY`/`ANTHROPIC_API_KEY`/
`ANTHROPIC_AUTH_TOKEN` from `shell_environment_policy.filters` (prevents
those values reaching any shell command the delegated model itself tries to
run inside its sandbox). This package's own audit trail
(`execution.json`/`stdout.txt`/`stderr.txt` under
`$XDG_STATE_HOME/agent-delegation/delegate_runs/`) never serializes the
environment and never contains the key.

Do not modify `codex-deepseek`, `codex-minimax`, `claude-deepseek`,
`claude-minimax`, or the two Codex provider profiles/catalogs to "simplify"
credential handling — they were hardened independently of this repository
and this integration deliberately treats them as a black box, invoking them
exactly as installed.

## Reasoning effort

DeepSeek's model catalog (`~/.codex/model-catalogs/deepseek-v4.json`)
exposes three distinct levels for both `deepseek-v4-pro` and
`deepseek-v4-flash`: `low`, `high`, `max` — there is no `medium`. MiniMax's
catalog (`~/.codex/model-catalogs/minimax-m3.json`) exposes only `none` and
`high`. Neither catalog's levels line up with the `low`/`medium`/`high`
labels this project's other delegates use, so do not assume a shared
meaning across providers.

For this first integration, both DeepSeek routes and the MiniMax route are
pinned to **`high`** — DeepSeek's and MiniMax's own catalog-declared
default, and the level MiniMax's existing local profile
(`~/.codex/minimax.config.toml`) was already configured with. This is a
conservative, already-proven-locally choice, not an invented flag. A
cheaper, thinking-disabled mode may exist for DeepSeek (`low`) or MiniMax
(`none`) for mechanical work, but is not wired up here pending explicit
verification that it behaves as documented.

## Disabled by default

`deepseek`, `minimax`, `deepseek-pro`, `deepseek-flash`, and `minimax-m3`
all default to **disabled**, with reason `experimental PAYG; benchmark
pending` — both on a brand-new install and when an existing
`config.toml` (predating these entries) is loaded; see
`delegation.config._default_entry`. Nothing in this project enables them
automatically, ever. Enable one explicitly:

```bash
delegate-config enable-provider deepseek
delegate-config enable deepseek-pro
delegate-config enable deepseek-flash

delegate-config enable-provider minimax
delegate-config enable minimax-m3
```

Or through the interactive `delegate-config` checkbox screen, where they
render with a `PAYG · experimental` tag distinguishing them from the
existing subscription/quota-based rows.

Disabling again afterward (`delegate-config disable-provider deepseek
--reason "..."`) is always safe and does not lose the model/transport
pinning — that lives in code (`delegation.core.DELEGATES`), not config.

## No automatic spending

This integration does not implement automatic top-up, does not enable
provider autobilling, does not mutate provider billing settings anywhere,
and does not automatically switch a task from a subscription route to a
PAYG route because another provider's quota looks low. `delegate-config` is
the only way availability changes, and only a human (or an explicit user
instruction) should invoke it for that reason — see
[DELEGATE_CONFIGURATION.md](DELEGATE_CONFIGURATION.md#ownership-this-is-user-owned-state).

## Smoke-test evidence

A smoke test (Claude Code primary, Sonnet 5) was attempted against tiny,
byte-verified read-only synthetic workspaces outside this repository,
immediately after installation. The first call (`ask-deepseek-flash`)
completed (exit 0, ~27s, real token usage billed) but hit a **harness/
environment failure, not a model-quality result**: the shell this call ran
from cannot initialize a bubblewrap sandbox at all —

```
bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted
```

— confirmed independently, at zero cost, with a bare `bwrap` invocation
outside of Codex entirely. `codex exec --sandbox read-only` (the mechanism
all three PAYG routes use) depends on bubblewrap, so `ask-deepseek-pro` and
`ask-minimax-m3` would have hit the identical wall from that same shell; per
the smoke-test protocol ("classify a harness failure, stop that route, do
not convert it into a model-quality score, no automatic retry"), the
remaining two calls were not attempted rather than spending PAYG balance to
reproduce a known, unrelated environment limitation.

This is a limitation of that specific execution environment (a sandboxed
shell nested inside another sandbox, without the namespace capabilities
bubblewrap needs), not of this integration or of DeepSeek/MiniMax — the
same delegates' non-sandboxed operations (`--version`, `--help`, credential
retrieval) all worked correctly from that shell, and `codex exec` is
expected to work normally from an ordinary user shell. Re-attempt the
smoke test for `deepseek-pro` and `minimax-m3` from an environment where
`bwrap --unshare-net --dev /dev --ro-bind / / /bin/true` succeeds first —
that single check is a free, no-model way to confirm the sandbox will work
before spending anything.

All three routes were left `disabled` throughout and after — none was ever
enabled during this smoke test, so the "disabled by default" policy above
was never actually exercised as an enable/disable cycle; the one completed
call worked without any config change because `run_consultation` does not
gate on `delegate-config`'s enabled state — see
[DELEGATE_CONFIGURATION.md](DELEGATE_CONFIGURATION.md).

## Future benchmark protocol

These routes are not assigned a task-specific role (see
[DELEGATION_POLICY.md](DELEGATION_POLICY.md)) until they go through this
project's actual benchmark harness (`benchmark/`), reusing the existing
frozen tasks/fixtures and historical Terra/Sonnet/Gemini/Luna/Haiku
comparator evidence rather than rerunning it. Until that happens, treat any
apparent quality difference from a smoke test as anecdotal, not evidence.
