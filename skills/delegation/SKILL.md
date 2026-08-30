---
name: delegation
description: >
  Teaches an agent that read-only delegation to another model (Gemini Flash,
  Claude Haiku/Sonnet) is available as installed global commands, when it's
  worth using, and how to check what's currently eligible. Use when deciding
  whether to consult another model, when the user asks about delegation
  options, or before invoking ask-flash/ask-haiku/ask-sonnet/ask-terra/ask-luna/
  delegate-status.
---

# Delegation

You can consult another model read-only through installed global commands.
This is optional capacity, not a requirement, and this skill is a thin
discovery/judgement layer — it teaches when and how, not safety mechanics.
All enforcement (recursion prevention, scope validation, the self-provider
guard) lives in the installed code, not here.

## SAME-PROVIDER WORK USES NATIVE AGENTS

This is a routing invariant, not a preference:

- **Codex/OpenAI primary:** Terra and Luna are same-provider workers. Use
  native Codex agents. Never use `ask-terra` or `ask-luna` merely to launch
  another Codex process for ordinary same-provider work.
- **Claude Code/Anthropic primary:** Sonnet and Haiku are same-provider
  workers. Use native Claude subagents. Never use `ask-sonnet` or `ask-haiku`
  merely to launch another Claude process for ordinary same-provider work.
- **Cross-provider:** Claude Code may use `ask-terra`/`ask-luna`; Codex may
  use `ask-sonnet`/`ask-haiku`. These are valid because the target provider
  differs from the primary.
- **Gemini primary:** preserve the same-provider native-agent rule; use native
  Gemini agents where supported and do not use `ask-flash` merely to call
  Gemini again.

`delegate-status --primary codex` therefore reports Terra/Luna as
`native-only`, while `delegate-status --primary claude-code` reports enabled,
executable-backed Terra/Luna routes as `available`. The reverse holds for
Sonnet/Haiku. This avoids recursive CLI orchestration, preserves host-native
supervision, avoids unnecessary context/process overhead, and keeps
provider-recursion semantics explicit.

## Canonical external-consultation workflow

Use this sequence for every external consultation:

1. Check effective availability without making a model call:

   ```bash
   delegate-status --primary codex
   # or, for Claude Code:
   delegate-status --primary claude-code
   ```

2. Choose only routes reported as `available`. Same-provider routes are
   `native-only`; disabled or missing-executable routes are not substitutes.
3. Prepare the minimum necessary scoped workspace and its read-only marker.
4. Invoke the installed wrapper and capture its stdout and stderr:

   ```bash
   ask-flash --workspace /absolute/scoped-copy \
     --prompt-file /absolute/consultation-task.md --primary codex
   ask-terra --workspace /absolute/scoped-copy \
     --prompt-file /absolute/consultation-task.md --primary claude-code
   ask-luna --workspace /absolute/scoped-copy \
     --prompt-file /absolute/consultation-task.md --primary claude-code
   ask-deepseek-flash --workspace /absolute/scoped-copy \
     --prompt-file /absolute/consultation-task.md --primary codex
   ask-deepseek-pro --workspace /absolute/scoped-copy \
     --prompt-file /absolute/consultation-task.md --primary codex
   ask-minimax-m3 --workspace /absolute/scoped-copy \
     --prompt-file /absolute/consultation-task.md --primary codex
   ```

5. Read the textual consultation returned on stdout. This is the normal
   result channel. Do not wait for or search for a review file unless the task
   specifically asked the delegate to create one; delegates are not required
   to create files.
6. Extract useful findings, verify them against primary evidence, and
   integrate only verified conclusions.
7. If multiple delegates were used, record material agreement, disagreement,
   and unique useful findings. Do not invent disagreement when none was
   returned.

The wrapper exits 0 only for a textual consultation result. A delegate process
that exits 0 with blank stdout is surfaced as a model/response failure. A
meaningful textual response such as “nothing material to add” is a valid
no-addition result. The response is also retained in the audit run directory
as `stdout.txt`; `stderr.txt` contains diagnostics and `execution.json`
contains status and exit metadata. The evidence summary is on wrapper stderr,
so it does not contaminate the consultation stdout stream.

## Defaults

- Delegation is allowed by default unless the user says otherwise for this
  session or task.
- You, the primary agent, stay the owner: architecture, integration,
  verification, and the final answer are yours regardless of what a delegate
  returns.
- Prefer your own native subagent/task facility for same-provider work over
  an external wrapper. Do not externally delegate back into your own
  provider — `delegate-status` will show this as `native-only`, and the
  wrapper itself rejects it if you declare your identity. In particular,
  Codex uses native Terra/Luna agents and Claude Code uses native
  Sonnet/Haiku subagents.
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
ask-terra  --workspace /absolute/scoped-copy --prompt-file /absolute/task.md --primary <your-identity>
ask-luna   --workspace /absolute/scoped-copy --prompt-file /absolute/task.md --primary <your-identity>
ask-haiku  --workspace /absolute/scoped-copy --prompt-file /absolute/task.md --primary <your-identity>
ask-sonnet --workspace /absolute/scoped-copy --prompt-file /absolute/task.md --primary <your-identity>
ask-deepseek-flash --workspace /absolute/scoped-copy --prompt-file /absolute/task.md --primary <your-identity>
ask-deepseek-pro --workspace /absolute/scoped-copy --prompt-file /absolute/task.md --primary <your-identity>
ask-minimax-m3 --workspace /absolute/scoped-copy --prompt-file /absolute/task.md --primary <your-identity>
```

Capture both streams. The delegate's consultation is returned on stdout; the
wrapper's evidence path and diagnostics are on stderr. The response itself is
the primary output. Do not confuse the audit path or absence of a generated
review file with the consultation result.

## Optional experimental PAYG delegates

`ask-deepseek-pro`, `ask-deepseek-flash`, and `ask-minimax-m3` exist as the
same kind of read-only consultation wrapper, routed through independently
verified Codex provider-profile launchers (`codex-deepseek`/`codex-minimax`)
rather than OpenAI's own Codex inference — see
[docs/PAYG_DELEGATES.md](../../docs/PAYG_DELEGATES.md) for the transport
distinction. They are **experimental PAYG routes**: a two-task objective +
blind-review benchmark has now evaluated them (see
[docs/PAYG_BENCHMARK_2026-08.md](../../docs/PAYG_BENCHMARK_2026-08.md) and
[docs/DELEGATION_POLICY.md](../../docs/DELEGATION_POLICY.md) for the
evidence-guided per-route roles), but they remain **disabled by default and
metered/opt-in** on every install — evidence about quality does not change
that. Do not mechanically prefer DeepSeek Flash for every task just because
it led that crossover; apply the same task-fit judgement you would for any
other route.

They default to **disabled** on every install; a disabled route in
`delegate-status` means exactly that — do not route around it by invoking
the wrapper directly, and do not ask the user to enable one merely to try
it out. Only use one if `delegate-status --primary <your-identity>` already
reports it `available` (the user explicitly enabled it via `delegate-config`
or `delegate-config enable deepseek-pro`/`deepseek-flash`/`minimax-m3`).
Because each call draws down a metered balance, treat one as a deliberate,
non-default choice, not a first reach — and remember these routes reach
DeepSeek/MiniMax inference specifically, not Codex's own OpenAI models, even
though the transport is `codex exec`; the self-provider guard below already
accounts for this and will reject/allow correctly regardless of which CLI
you are.

Give the delegate the minimum necessary scope:

1. A dedicated directory with only files safe to disclose — no credentials,
   no unrelated project data, no symlinks.
2. `.delegation-scope.json` containing `{"mode": "read-only"}`.
3. A specific task in the prompt, not the whole surrounding context.

Read-only consultation is the default and, in this version, the only
supported mode — no wrapper here grants write access.

## After a delegate responds

Treat every claim as a hypothesis, not a fact. Read the returned stdout first,
then read the cited file:line evidence yourself, re-run any verification
command it proposes if safe, and only act once you've independently confirmed
it. Logs land under the installed state directory (`delegate-status` shows the
path) as `prompt.md`/`stdout.txt`/`stderr.txt`/`execution.json` — plain files,
read them like any other. The files are an audit backup, not a required
delegate deliverable.

## Failure diagnosis and bounded recovery

If an `ask-*` command fails, inspect its exit status, stderr, evidence path,
`execution.json`, route status, and scope declaration before classifying it.
Classify the cause as one of: availability/config, scope/sandbox,
recursion/provider guard, launcher/executable, authentication,
provider/API/transport, wrapper/runtime, or model/response. A non-zero exit is
not a model-quality score, and a missing review file is not evidence of any
failure. Never report a delegate as “non-functional” without the underlying
diagnosis.

If the cause is safe, local, bounded infrastructure within the task scope,
repair that cause and retry at most once. Never use a blind retry loop or
silently substitute another provider. If no safe repair is possible, report
the exact blocker and continue with the primary task where possible. Do not
expose secrets while inspecting diagnostics.

Delegation is complete only when each requested external route is accounted
for as one of:

- **Success:** textual response returned, inspected, and useful findings
  integrated or explicitly rejected after verification.
- **Valid no-addition:** the delegate explicitly returned a meaningful
  statement that it had nothing material to add.
- **Diagnosed infrastructure failure:** the exact failure category and reason
  are known.
- **Diagnosed model/response failure:** the provider completed, but its
  response was empty, malformed, or unusable.

An ambiguous “no usable textual review records” state is not completion.

## Shared OpenAI-compatible/vLLM routes

Some machines may have an explicitly configured named route for a shared
OpenAI-compatible vLLM service. Check `delegate-status --primary <identity>`
first, then use `ask-vllm <named-route>` only for tightly
scoped, read-only consultation when the route is deliberately selected. It is
not an automatic fallback for any other provider and must not be used for
parallel fan-out, speculative requests, nested delegation, or unconstrained
coding-agent sessions. The direct adapter sends one bounded Chat Completions
request, defaults to `enable_thinking = false`, uses a machine-local
single-request lock, and has no automatic retry or cloud substitution.

Shared-compute routes must respect their configured concurrency and runtime
policy. In particular, do not perform speculative fan-out, do not substitute
another provider automatically, and respect a configured non-thinking default.
An unavailable server is an infrastructure-availability failure, not evidence
that the model produced a poor response; keep those diagnoses separate.

Before invoking a named shared OpenAI-compatible route, inspect its effective
local capabilities with `delegate-status --primary <primary>`. Respect the
reported output budget: never request `max_tokens` above the configured local
route cap, and choose a task and output format that fit. If the task does not
fit, do not invoke that route. A local validation exit such as exit code 2
means no inference occurred and is not model-quality evidence. Distinguish a
local route policy from a remote server/model maximum. A suitable alternate
provider may be selected before invocation when policy and availability allow,
but do not silently switch providers after validation failure.

The named route configuration and redacted JSONL reliability records are
machine-local; never commit them or put credentials in prompts, config,
fixtures, logs, or diagnostics. See
`docs/VLLM_DELEGATES.md` in the source repository for the configuration and
reporting contract. A Codex primary-model configuration is a separate audit:
do not assume a Chat Completions-only endpoint is compatible with Codex's
Responses transport.

## Timeout and cancellation semantics

The default `ask-*` timeout is 300 seconds. If a shorter operational bound is
needed, pass it explicitly, for example:

```bash
ask-haiku --workspace /absolute/scoped-copy \
  --prompt-file /absolute/task.md --primary codex --timeout 90
```

Do not infer a timeout merely because `stdout.txt` or `execution.json` has not
appeared while the command is still running. Those audit files are finalized
after the delegate subprocess returns or after the wrapper catches its own
timeout; they are not a live-progress indicator. A genuine wrapper timeout is
recorded as exit code `124` with `timed_out: true` and finalized audit files.

If a parent agent, shell supervisor, or operator manually kills the wrapper
before that point, the run may have no finalized audit record. Classify that as
an externally terminated/incomplete infrastructure run, not as a wrapper
timeout or model failure. Do not terminate a healthy wrapper solely because
its audit files are still absent; either wait for the configured bound or set
the bound explicitly before invoking it.

## Recursion is prohibited

An approved wrapper (`ask-flash`/`ask-haiku`/`ask-sonnet`) refuses to run
if it's already executing inside a delegated context. Never work around
this. A delegate must never call another delegate.
