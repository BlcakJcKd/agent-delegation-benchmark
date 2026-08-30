# Delegation policy

## Purpose and default

This policy translates the completed synthetic benchmark into a conservative
operational practice. It is evidence-guided rather than a claim that one
provider is universally better. The default is **read-only consultation**:
the primary owner keeps authority, receives an independent view, and decides
what (if anything) to change.

Never send a delegate more context than needed. Give it a dedicated workspace,
an explicit task, an allowed scope, and an expected response. State: **do not
modify files; do not access parent directories, credentials, unrelated data, or
other workspaces; do not delegate again.** A delegate is not an authority to
merge, publish, purchase, send messages, or handle secrets.

The primary agent remains responsible for integration, validation, and the
final answer. Delegation is optional: use it only when independent reasoning,
parallelism, specialist experience, or quota preservation outweighs its
context/latency cost.

## Canonical result contract

The `ask-*` invocation itself is the consultation channel. On a successful
call, the wrapper exits 0 and returns the delegate's textual response on
stdout. The wrapper durably retains the same response as private `stdout.txt`
in the audit run directory before finalizing success; `stderr` carries
launcher/provider diagnostics and the evidence summary, while `execution.json`
records exit and response metadata including `response_recorded: true` and the
run-relative response locator. The primary must capture and read stdout before
claiming the consultation is complete, and can recover that retained response
from the evidence directory if terminal output is lost. A delegate does not
need to create a review file, and the absence of one is not a failure signal.

The normal success invariant is `exit_code=0`, `response_status=text-returned`,
non-empty response text, and `response_recorded=true`. HTTP success alone is
not enough. If text exists but cannot be durably retained, the wrapper reports
a distinct `response-retention` infrastructure failure, preserves the fact
that the provider completed where known, and does not retry automatically.

The only valid empty-looking outcome is a meaningful textual response that
explicitly says there is nothing material to add. Blank stdout after a zero
exit is a model/response failure. A non-zero exit requires diagnosis from
stderr, `execution.json`, route status, and scope evidence; it is not by
itself a model-quality result.

## SAME-PROVIDER WORK USES NATIVE AGENTS

This is an explicit routing invariant:

- A Codex/OpenAI primary uses native Codex agents for Terra/Luna. It must not
  use `ask-terra` or `ask-luna` merely to recursively launch another Codex
  process.
- A Claude Code/Anthropic primary uses native Claude subagents for
  Sonnet/Haiku. It must not use `ask-sonnet` or `ask-haiku` merely to
  recursively launch another Claude process.
- Claude Code -> `ask-terra`/`ask-luna` is valid cross-provider delegation.
  Codex -> `ask-sonnet`/`ask-haiku` is valid cross-provider delegation.
- Gemini same-provider native-agent protections remain in force: a Gemini
  primary uses native Gemini agents where supported, not `ask-flash` merely to
  call Gemini again.

The native rule avoids recursive CLI orchestration, preserves host-native
agent supervision, avoids unnecessary context/process overhead, and keeps
provider-recursion semantics clean. `delegate-status --primary codex` shows
Terra/Luna as `native-only`; `delegate-status --primary claude-code` shows
enabled Terra/Luna as external/available when Codex is configured and on
PATH. Claude's Sonnet/Haiku are correspondingly `native-only`.

## External delegation procedure

```text
delegate-status --primary codex       (or --primary claude-code)
  -> select only effectively available external routes
  -> prepare minimum scoped read-only context
  -> invoke ask-* and capture/read textual stdout
  -> verify findings against primary evidence
  -> record material agreement/disagreement across delegates
  -> integrate only verified conclusions
```

Same-provider work uses native agents. Same-provider work uses the host's
native agents. Do not externally call the
same provider to simulate a native subagent. Availability is machine-local and
user-owned; always inspect `delegate-status` rather than assuming a route is
enabled. The evidence-guided routing guidance below remains unchanged: Flash
is useful subscription/quota capacity, DeepSeek V4 Flash is the preferred
tested general PAYG route when enabled, DeepSeek V4 Pro is for genuinely
difficult bounded work, and MiniMax M3 is a provider-diverse alternative.

## Prompt-author block

Copy this compact block into a Codex or Claude prompt when delegation is part
of the task:

```text
DELEGATION

Check:
    delegate-status --primary codex
or:
    delegate-status --primary claude-code

Cross-provider wrappers:
    ask-terra
    ask-luna
    ask-sonnet
    ask-haiku
    ask-flash
    ask-deepseek-flash
    ask-deepseek-pro
    ask-minimax-m3

SAME-PROVIDER:
    Codex -> native Codex agents for Terra/Luna
    Claude -> native Claude subagents for Sonnet/Haiku

Only use an ask-* wrapper when the target is genuinely cross-provider for the
current primary.

For each external delegate:
    invoke wrapper; allow it to run until its declared timeout; capture/read
    textual stdout; verify findings; reconcile disagreement; integrate only
    verified conclusions.

Do not expect a generated review file.
Do not interpret absence of a generated file as absence of a consultation.
Do not kill a delegate merely because it is quiet.
Genuine timeout = exit 124 + timed_out:true.
Diagnose infrastructure/provider/model failures before labelling a delegate
non-functional.
```

## Evidence-based routing

| Delegate | Good initial uses | Escalate / keep with primary when |
|---|---|---|
| Gemini 3.7 Flash Medium | exploratory plots, data inspection, repository reconnaissance, test analysis, routine Python analysis, straightforward debugging, bulk/routine review, independent hypotheses | task is scientifically sensitive, needs minimal implementation guarantees, or supplied context does not let it verify a conclusion |
| Claude Haiku Medium | cheap Claude-side implementation/review, straightforward fixes, routine analysis, test suggestions, preserving Sonnet quota | a task needs deeper design judgment, stronger writing, or a broad integration plan |
| Claude Sonnet Medium | substantial well-scoped implementation, document/build tooling, stronger review, scientific drafting, escalation after a cheap consultation | requirements are ambiguous, cross-cutting, security-sensitive, or the result needs final ownership/synthesis |
| Codex Terra Medium | primary owner, difficult integration, final synthesis, key verification, scientifically sensitive interpretation | use it directly when delegation overhead is larger than the task |
| Codex Luna Medium | simple Codex-native work when the primary runtime provides an explicit native subagent facility | do not recursively spawn `codex exec` from a Codex worker; use a native facility only if the active runtime exposes one |

Gemini 3.1 Pro Low is an historical comparator, not the operational default.
Flash is the preferred Antigravity configuration unless new, versioned evidence
changes that conclusion.

This table describes what's *evidence-guided*, not what's currently
*eligible* on a given machine. A route can be persistently disabled by the
user (e.g. quota exhausted) independent of this guidance — check
`delegate-status` before delegating; see
[DELEGATE_CONFIGURATION.md](DELEGATE_CONFIGURATION.md) for the config that
governs it and who's allowed to change it.

### Experimental PAYG routes: evidence-guided, still opt-in

`deepseek-pro`, `deepseek-flash`, and `minimax-m3` (via `ask-deepseek-pro`/
`ask-deepseek-flash`/`ask-minimax-m3`) exist as optional, pay-as-you-go
transport through independently verified Codex provider-profile launchers —
see [PAYG_DELEGATES.md](PAYG_DELEGATES.md). They are deliberately kept
**out of the table above**, not because they are unevaluated (they now are
— see [PAYG_BENCHMARK_2026-08.md](PAYG_BENCHMARK_2026-08.md)), but because
they remain **disabled by default and metered/opt-in**, unlike every route
in the main table, which is available without a per-call cost decision. The
completed benchmark changes what's *known*, not what's *enabled*.

| Delegate | Good initial uses (evidence-guided) | Caveats |
|---|---|---|
| DeepSeek V4 Flash / high | routine coding, debugging, repository analysis, plotting/data work, scientific drafting, bounded reasoning, independent review | fastest and best-scoring of the three PAYG candidates on both tested screens (objective + blind); still a two-task, single-attempt, single-reviewer sample — not a claim of frontier-model equivalence |
| MiniMax M3 / high | plotting/visual diagnostics specifically, implementation alternatives, second opinions, provider/model diversity, independent critique | matched Flash/Pro objectively; best blind diagnostic-plot score but slower and more token-hungry than Flash, and slightly weaker blind writing calibration |
| DeepSeek V4 Pro / high | keep as a specialist/experimental route for genuinely difficult work Flash may fail at (architecture reasoning, subtle numerical reasoning, difficult cross-file debugging, adversarial review, complex scientific reasoning) — that use case is untested | materially slower than Flash on the routine screen; weakest blind plot score of the three; current evidence does **not** justify preferring it over Flash for routine delegated work |

Do not mechanically route every task to DeepSeek Flash simply because it
led this crossover — task fit, native-vs-external routing, verification
cost, provider diversity, subscription quota, and PAYG spending all remain
relevant per-task considerations, same as for the main table. These three
routes default to **disabled** and require an explicit `delegate-config`
opt-in per machine; run `delegate-status --primary <identity>` before
considering one, and never enable one on the user's behalf.

## Escalation pattern

```text
primary owner
  -> cheap, read-only delegate (Flash or Haiku) when useful
  -> reconcile claims against local evidence
  -> Sonnet for a deeper independent review or well-scoped implementation
  -> Terra retains integration, sensitive interpretation, and final verification
```

This is a menu, not a mandatory pipeline. Do not use two delegates merely to
create apparent consensus; reconcile against tests, documentation, and the
actual files.

## When not to delegate

- The task is trivial or the context-extraction cost exceeds the work.
- The delegate cannot receive a safe, least-privilege workspace.
- The result cannot be independently checked.
- The task contains credentials, regulated/private data, or data that should
  not cross a provider boundary.
- The proposed path would make an agent recursively delegate or invoke an
  unbounded automation loop.

## Operational wrappers

Two equivalent interfaces invoke the same `delegation` package: the
development wrappers `bin/ask-terra`, `bin/ask-luna`, `bin/ask-flash`,
`bin/ask-haiku`, `bin/ask-sonnet`
(`python -m delegation.cli <name>`, working directly from a checkout), and
the installed, cross-project commands `ask-terra`/`ask-luna`/`ask-flash`/
`ask-haiku`/`ask-sonnet` produced by `scripts/install-user-delegation.sh` (see
[USER_INSTALLATION.md](USER_INSTALLATION.md)). Both implement consultation
only. Both require a dedicated workspace containing `.delegation-scope.json`
with:

```json
{"mode": "read-only"}
```

The marker is an explicit operator assertion, not a security boundary.
Prepare that directory with only the files safe to disclose and no symlinks.
Logs are written under the XDG state directory
(`$XDG_STATE_HOME/agent-delegation/delegate_runs/`, falling back to
`~/.local/state/agent-delegation/delegate_runs/`; override with
`--log-root`), never inside the consulted workspace and never inside this
repository by default. Each log contains the prompt, stdout, stderr, exit
code, elapsed time, requested model/effort, cwd, declared caller/primary,
and a redacted argv; it never serializes the environment.

Example (do not run against a real project without checking the scope):

```bash
ask-flash --workspace /absolute/scoped-copy \
  --prompt-file /absolute/consultation-task.md --timeout 300 \
  --primary claude-code
```

`--primary` is optional but enables the self-provider guard: a wrapper
rejects being invoked for its own declared primary's provider (e.g. Claude
primary calling `ask-haiku`/`ask-sonnet`) before launching anything, since
same-provider work should go through that host's native agent capability
instead. This is distinct from the recursion-depth guard below — see
[CLAUDE_CODE_ORCHESTRATION.md](CLAUDE_CODE_ORCHESTRATION.md) for the
difference. Run `delegate-status --primary <identity>` first to see the
effective landscape without making any model call.

Before a real consultation, run the local, no-model wrapper validation:

```bash
python -m delegation.preflight
```

The read-only mechanisms are intentionally narrow:

- Flash: documented `agy --mode plan --sandbox`; prompt is final after `-p`.
- Haiku/Sonnet: Claude `--safe-mode --permission-mode plan`, with both the
  available-tools and pre-approved tool sets restricted to `Read,Glob,Grep`.
  No `Write`, `Edit`, or `Bash` is offered.
- Terra/Luna use the normal `codex exec --sandbox read-only` path for
  non-Codex primaries; the self-provider guard blocks those wrappers for a
  Codex primary, which must use native agents.

No wrapper uses `dangerously-skip-permissions`, `bypassPermissions`, broad
`Bash`, `danger-full-access`, or automatic approval flags.

## Current limitations and implementation delegation

The user-level `ask-*` foundation does **not** implement writing delegation.
The benchmark separately supports an optional, machine-local command-agent
adapter for explicitly selected copied-workspace experiments; it is not a
general delegation route or an automatic fallback. Any future general
write-capable delegation mode must be separately approved with a copied
workspace, task-specific command allowlist, diff review, tests, and an
explicit hand-off contract. In particular,
Claude's documented CLI exposes no Codex-equivalent hard workspace-read
sandbox; its CWD and explicit tools are operational controls, not a complete
filesystem containment guarantee. Antigravity's exact plan/sandbox semantics
also remain product-defined. Preserve least privilege by preparing the scoped
copy before invoking either service.

For Codex, prefer a native primary-runtime subagent/task facility when the
active Codex surface provides one. Terra/Luna's external wrappers are for
non-Codex primaries only; a Codex primary must not use them to recursively
start another Codex CLI. Keep a depth-one architecture: a primary may ask a
cross-provider delegate; a delegate must never ask another delegate.
