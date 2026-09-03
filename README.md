# Ekalavya

Ekalavya is a stable delegation/control-plane abstraction for primary agents.
It separates command intent, capability profiles, model identities, explicit
resolution, execution adapters, evidence, and a private historical ledger.
The repository also contains the Ekalavya Benchmark subsystem; benchmarking
is not the product identity.

The primary agent owns routing. A profile default is an explicit choice when
the primary invokes it, not hidden autonomous provider selection. Ekalavya
does not silently fail over. Codex/OpenAI work uses native Codex agents for
same-provider Terra/Luna, Claude uses native Claude subagents for Sonnet/Haiku,
and Gemini uses native Gemini facilities. A same-provider external resolution
returns `same-provider-native-required` so the primary can decide what to do.

Profiles represent capabilities such as `coder`, `reviewer`, or
`researcher`; candidates preserve provider, family, exact provider model ID,
reasoning, harness, transport, and (when known) local serving metadata.
The live catalogue intentionally stays small: current, previous supported
fallback, and explicit new candidates. Discovery marks candidates; it never
promotes a newer model automatically, and retired models remain in history.

The private ledger at `~/.local/state/ekalavya/ledger.sqlite3` records
requested intent separately from resolved execution, benchmark/task/evaluator
hashes, request and tool telemetry, resource observations, pricing snapshots,
promotion/retirement decisions, and references to private raw evidence. API
cost, calculated cost, subscription cost, and local resource usage are kept
separate; unavailable spend is represented as `null`, never guessed.

## Commands

```text
ekalavya run <profile> [--provider P --family F --model ID --reasoning R
                        --harness H --workspace DIR --prompt-file FILE]
ekalavya status [--json]       # network-free overview
ekalavya config migrate        # additive, reversible legacy migration
ekalavya models                # catalogue only; no provider discovery
ekalavya models refresh --source FILE  # explicit, file-driven discovery
ekalavya profiles
ekalavya history [--json]
ekalavya spend [--json]
ekalavya bench                 # benchmark subsystem entry point
ekalavya doctor [--json]
```

`eka` is an optional shorthand created by the user-level installer only when
it is absent or already points to Ekalavya. An unrelated executable is never
overwritten. Existing `ask-*`, `delegate-status`, `delegate-config`, and
`ask-vllm` commands remain compatibility interfaces with their historical
semantics.

`status`, `models`, `profiles`, `history`, and `spend` are read-only. The
explicit `models refresh` path accepts provider discovery data and records new
entries as candidates; it does not download models, start servers, or alter a
profile default. Persistent provider/model configuration remains user-owned.

## Safety and evidence

External compatibility wrappers retain closed stdin, scoped workspaces,
symlink/parent-escape checks, recursion protection via
`AGENT_DELEGATION_DEPTH`, process-group and timeout semantics, and atomic
private response retention. Writable benchmark runs use disposable copies and
hidden evaluators outside candidate workspaces. Private configuration,
provider endpoints, credentials, raw traces, and machine-specific telemetry
must stay outside Git.

## Benchmark subsystem

The existing frozen benchmark and Benchmark V2 remain operational under
`benchmark/`. Run the no-model checks with:

```bash
python -m unittest discover -s tests -q
python -m benchmark.runner check
python -m benchmark.runner preflight --agents codex,claude,agy --tasks research_python
```

Benchmark identity includes suite/version, benchmark Git SHA, task family and
variant, content/prompt/evaluator hashes, candidate identity, harness, and
reasoning. A small longitudinal core can remain stable while evolving suites
such as Benchmark V2 provide fresh discrimination.

## Installation

The supported user-level installation remains self-contained via pipx:

```bash
scripts/install-user-delegation.sh
```

The installer does not require sudo, alter provider authentication, install a
serving engine, or modify model/GPU settings. It copies the delegation skill
instead of linking it into the checkout, so installed commands remain usable
after the repository moves.
