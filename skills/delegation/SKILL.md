---
name: delegation
description: >
  Teaches an agent that read-only delegation to another model (Gemini Flash,
  Claude Haiku/Sonnet) is available as installed global commands, when it's
  worth using, and how to check what's currently eligible. Use when deciding
  whether to consult another model, when the user asks about delegation
  options, or before invoking ask-flash/ask-haiku/ask-sonnet/delegate-status.
---

# Delegation

You can consult another model read-only through installed global commands.
This is optional capacity, not a requirement, and this skill is a thin
discovery/judgement layer — it teaches when and how, not safety mechanics.
All enforcement (recursion prevention, scope validation, the self-provider
guard) lives in the installed code, not here.

## Defaults

- Delegation is allowed by default unless the user says otherwise for this
  session or task.
- You, the primary agent, stay the owner: architecture, integration,
  verification, and the final answer are yours regardless of what a delegate
  returns.
- Prefer your own native subagent/task facility for same-provider work over
  an external wrapper. Do not externally delegate back into your own
  provider — `delegate-status` will show this as `native-only`, and the
  wrapper itself rejects it if you declare your identity.
- Gemini Flash is useful high-quota external capacity, not a mandatory first
  choice. Do not consult it reflexively on every task.

## Before delegating: check what's eligible

Run this first — it makes zero model calls:

```bash
delegate-status --primary <your-identity>
```

Use `claude-code` if you are Claude Code, `codex` for Codex, `gemini` (or
`antigravity`) for Antigravity/Gemini, `manual` for a human-invoked call, or
omit `--primary` if genuinely unknown. This reports, per route, whether it's
configured enabled/disabled (with a reason if the user set one), whether
it's `external` (usable via a wrapper), `same-provider`/`native-only` (use
your own native mechanism instead — the wrapper will reject it), or
`disabled` (respect this; do not route around it), and whether the external
executable is actually on PATH. Add `--json` for machine-readable output.

Respect what you see. A disabled provider or route is user-owned
configuration (`delegate-config`) — read it, don't override it. If the user
gives a task-specific instruction ("don't use Codex for this"), treat that
as a session constraint on top of the persistent config, not a reason to run
`delegate-config` yourself. You may read and report config; you should not
change it on your own judgement (e.g. because you think quota looks low) —
persistent mutation is the user's call, made explicitly or via
`delegate-config` directly.

## When delegation is worth it

Delegate only when one of these holds:

- **Verification is materially cheaper than generation.** A delegate can
  scan a scoped workspace and return file:line evidence faster than you
  re-deriving it, and the claim is cheap for you to check against the real
  files.
- **Independent reasoning/critique adds value.** A second, differently
  biased read of the same evidence before you commit to a conclusion.

If neither applies, do the work directly.

Good candidates: repository reconnaissance, file:line evidence gathering,
targeted test-failure diagnosis, data/plot inspection, bounded analysis,
alternative hypotheses, a first-pass review, mechanical investigation that's
cheap to verify.

Keep for yourself: architecture, scientifically or security-sensitive
interpretation, difficult numerical reasoning, final integration, anything
expensive to independently verify.

## Invoking a delegate

```bash
ask-flash  --workspace /absolute/scoped-copy --prompt-file /absolute/task.md --primary <your-identity>
ask-haiku  --workspace /absolute/scoped-copy --prompt-file /absolute/task.md --primary <your-identity>
ask-sonnet --workspace /absolute/scoped-copy --prompt-file /absolute/task.md --primary <your-identity>
```

Give the delegate the minimum necessary scope:

1. A dedicated directory with only files safe to disclose — no credentials,
   no unrelated project data, no symlinks.
2. `.delegation-scope.json` containing `{"mode": "read-only"}`.
3. A specific task in the prompt, not the whole surrounding context.

Read-only consultation is the default and, in this version, the only
supported mode — no wrapper here grants write access.

## After a delegate responds

Treat every claim as a hypothesis, not a fact. Read the cited file:line
evidence yourself, re-run any verification command it proposes if safe, and
only act once you've independently confirmed it. Logs land under the
installed state directory (`delegate-status` shows the path) as
`prompt.md`/`stdout.txt`/`stderr.txt`/`execution.json` — plain files, read
them like any other.

## Recursion is prohibited

An approved wrapper (`ask-flash`/`ask-haiku`/`ask-sonnet`) refuses to run
if it's already executing inside a delegated context. Never work around
this. A delegate must never call another delegate.
