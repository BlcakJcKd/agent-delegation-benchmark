# Agent delegation benchmark

A small, synthetic, frozen-fixture benchmark for comparing Codex CLI, Claude Code, and
Antigravity CLI (`agy`). All existing `first-*` runs are **PILOT / HARNESS VALIDATION** evidence,
not controlled model-tier evidence; see [RUN_HISTORY.md](RUN_HISTORY.md).

The canonical methodology, incident record, frozen results, clean-machine
procedure, and future-model protocol are in
[docs/AGENT_BENCHMARK_HANDBOOK.md](docs/AGENT_BENCHMARK_HANDBOOK.md). The new
operational delegation layer is separate from immutable historical `runs/`; its
read-only consultation policy and wrappers are in
[docs/DELEGATION_POLICY.md](docs/DELEGATION_POLICY.md).

## Delegation as a user-level tool

This repository is also the source for an installable, cross-project
delegation runtime: `ask-flash`/`ask-haiku`/`ask-sonnet` for read-only
consultation, `delegate-status` for a zero-model-call view of what's
currently eligible, and `delegate-config` to persistently enable/disable
providers or routes. Once installed (`scripts/install-user-delegation.sh`),
none of this depends on this checkout still existing — see
[docs/USER_INSTALLATION.md](docs/USER_INSTALLATION.md) for the install
procedure and architecture, and
[docs/DELEGATE_CONFIGURATION.md](docs/DELEGATE_CONFIGURATION.md) for the
config schema and ownership rules. Claude-Code-specific orchestration
guidance is in
[docs/CLAUDE_CODE_ORCHESTRATION.md](docs/CLAUDE_CODE_ORCHESTRATION.md), and
a short entry point for any other agent is
[docs/LLM_HANDOFF.md](docs/LLM_HANDOFF.md).

## Method

Each of the six tasks has a fixed prompt in `tasks/prompts/` and starting files in `fixtures/`.
Their SHA-256 hashes are committed in `fixtures.lock.json`. The runner refuses to prepare a run
if this lock does not match, so prompts and starting files are frozen before contestants run.

For a run label, the runner copies each fixture independently to
`runs/<label>/<task>/<agent>/workspace/`, writes the same frozen task prompt into each workspace,
then starts each CLI with that workspace as its process working directory. It records the exact
command, wall-clock duration, exit/timeout status, raw stdout/stderr, changed files, any
JSON usage-like fields exposed by that CLI, and an automated evaluation. It does not edit a
contestant workspace after the CLI returns.

The selected tasks are intentionally small. Controlled results use named **matched practical
operating tiers**, not identical-compute configurations: provider model families, effort controls,
system prompts, tools, and internal compute differ.

| ID | Exercise | Primary evaluation |
|---|---|---|
| `research_python` | synthetic Python data analysis | exact JSON values |
| `diagnostic_plot` | matplotlib QC diagnostic | PNG + outlier JSON |
| `debug_package` | four seeded package defects | clean `unittest` run |
| `repository_review` | read-only seeded-issue review | hidden keyword manifest + edit check |
| `pandoc_pdf` | Markdown-to-Pandoc PDF | valid PDF signature |
| `scientific_writing` | Results/Discussion from numbers | evidence/rubric checks + blind review |

The seeded issue manifests live in `private_admin/manifests/`; they are not copied into
contestant workspaces. Never share `private_admin/` or `blind_map.json` with human evaluators.
Blind human-review files are copied to `runs/<label>/blind/` under opaque submission identifiers;
the private mapping remains in `blind_map.json`.

## Layout

```
benchmark/                 runner, adapters, fixture lock and evaluators
fixtures/                  public, identical starting material
tasks/prompts/             public, identical frozen prompts
private_admin/manifests/   administrator-only seeded issue ground truth
tests/                     harness tests only
runs/                      generated, ignored comparison workspaces and evidence
```

## Commands

```bash
python -m unittest discover -s tests -q
python -m benchmark.runner check
python -m benchmark.runner list --verbose
python -m benchmark.runner preflight --agents codex,claude,agy --tasks research_python
```

No run can rely on a CLI default model. Supply a chosen, explicit model for every contestant, or
use one of the fixed named tiers:

| Tier | Codex | Claude | Antigravity |
|---|---|---|---|
| `tier-a-medium` | `gpt-5.6-terra`, effort `medium` | `claude-sonnet-5`, effort `medium` | `gemini-3.1-pro-low` |
| `tier-b-cheap` | `gpt-5.6-luna`, effort `medium` | `claude-haiku-4-5-20251001`, effort `medium` | `gemini-3.7-flash-medium` |

The selected Antigravity model variants encode their Low/Medium designations; the harness does
not apply an additional undocumented effort override. Tier A addresses everyday medium-capability
delegation; Tier B addresses cheap/high-throughput routine work. Do not compare scores across
tiers as though they shared the same resource budget.

The no-model preflight intentionally fails until those choices are supplied; it never contacts a
model. After choosing a tier, inspect the exact argv templates first:

```bash
python -m benchmark.runner preflight \
  --tier tier-a-medium --agents codex,claude,agy --tasks research_python
```

Only after a passing preflight may a run start. `--timeout` defaults to 900 seconds per
contestant/task. A reused run label is rejected, preserving the original evidence.

## Adapters and safety

The adapters reflect the locally inspected help for the installed versions:

- Codex: `codex exec --sandbox workspace-write --cd <workspace> --json` plus an explicit
  configured reasoning effort.
  No approval override or dangerous bypass is used.
- Claude: `claude --output-format json --safe-mode --permission-mode auto --model <model> -p
  <prompt>`; its process current directory is the assigned workspace.
- Antigravity: `agy --output-format json --mode accept-edits --sandbox --model <model> -p
  <prompt>`. Its installed help offers no documented non-bypass autonomous mode beyond
  `accept-edits` plus sandboxing.

All configuration flags precede the final `-p <prompt>` for Antigravity. No permission-bypass or
dangerous flags are used. A passing preflight checks CLI versions/help flags, explicit model
configuration, fixtures, isolated-copy construction, private-material exclusion, required task
dependencies, and redacted argv templates. A missing executable prevents every contestant from
starting. Authentication failures are captured as individual non-zero CLI exits; the runner does
not try to authenticate or silently substitute another model.

Claude's `--worktree` is intentionally not used. The harness already builds a disposable copied
workspace per contestant; `--worktree` requires/rearranges Git worktrees and would add another
independent copy/isolation mechanism, complicating fixture equivalence without strengthening the
documented filesystem boundary.

## Fairness limits

This harness equalises prompts, initial files, order within a task, process cwd, explicit requested
models, and collection of evidence. It cannot make unlike products identical. Account entitlements,
system prompts, tool availability, shell/environment configuration, and sandbox strength differ.
Claude's displayed help has no documented equivalent to Codex's workspace sandbox; its CWD is an
operational boundary rather than a cryptographic isolation boundary. `agy` may likewise have
product-specific sandbox semantics, and its `accept-edits` mode may still request intervention for
some local commands. Run on the same machine, with the same network policy and no unrelated
background load; record CLI versions with the run.

Usage figures are retained only as each CLI reports them. They are intentionally not normalized
or presented as comparable token counts, because the CLIs may expose different definitions or no
usage fields at all. Automated scores are deliberately narrow. Inspect blind plot and prose
outputs separately, and treat all scores as decision support rather than a universal ranking.

Run-level metadata records the named tier, requested model and effort configuration, and a
separate observed model field when the CLI emits one. `benchmark.tiers.PILOT_RUN_LABELS` is the
authoritative exclusion list for all controlled aggregate analysis.
