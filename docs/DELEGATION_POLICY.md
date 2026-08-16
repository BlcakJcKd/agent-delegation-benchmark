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
development wrappers `bin/ask-flash`, `bin/ask-haiku`, `bin/ask-sonnet`
(`python -m delegation.cli <name>`, working directly from a checkout), and
the installed, cross-project commands `ask-flash`/`ask-haiku`/`ask-sonnet`
produced by `scripts/install-user-delegation.sh` (see
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
- Codex is not wrapped recursively. A reference argv in `delegation.core`
  demonstrates `codex exec --sandbox read-only` for a future direct pathway.

No wrapper uses `dangerously-skip-permissions`, `bypassPermissions`, broad
`Bash`, `danger-full-access`, or automatic approval flags.

## Current limitations and implementation delegation

The current foundation does **not** implement writing delegation. That must be
a separately approved mode with a new copied workspace, task-specific command
allowlist, diff review, tests, and an explicit hand-off contract. In particular,
Claude's documented CLI exposes no Codex-equivalent hard workspace-read
sandbox; its CWD and explicit tools are operational controls, not a complete
filesystem containment guarantee. Antigravity's exact plan/sandbox semantics
also remain product-defined. Preserve least privilege by preparing the scoped
copy before invoking either service.

For Codex, prefer a native primary-runtime subagent/task facility when the
active Codex surface provides one. The locally inspected `codex exec` 0.147.0
help has no native subagent subcommand, so recursively starting another Codex
CLI is not adopted here. Keep a depth-one architecture: a primary may ask a
delegate; a delegate must never ask another delegate.
