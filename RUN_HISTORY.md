# Benchmark run history

## Prior runs — PILOT / HARNESS VALIDATION ONLY

The following preserved run labels are operational pilot evidence only and are excluded from every
controlled matched-practical-tier aggregate: `first-comparison`, `first-valid-comparison`,
`first-valid-codex-repair`, and `first-valid-codex-terra`.

`first-comparison` remains an **INVALID / HARNESS FAILURE** diagnostic. The other three runs
validated repaired adapter behavior but used unmatched configurations (Codex Terra/high, Claude
Sonnet/default, Gemini Flash/high), so they are not controlled model-tier evidence.

## `first-comparison` — INVALID / HARNESS FAILURE

Preserved unchanged at `runs/first-comparison/`; do not aggregate its evaluator scores.

- Codex CLI rejected an adapter argument before a model session started.
- Claude was blocked by a non-interactive command approval request and did not create `answer.json`.
- Antigravity received later options as prompt content and did not receive the benchmark task.
- The original runner did not report individual failures at the terminal.

This record is administrative metadata only; it does not modify the failed run artifacts.

## `tier-b-controlled-002` — PARTIAL CONTROLLED EVIDENCE

Preserved unchanged at `runs/tier-b-controlled-002/`.

- Luna's `diagnostic_plot` attempt completed validly and is retained for Tier B.
- Haiku's plot attempt was externally interrupted after it created workspace files but before the runner could write complete execution/evaluator evidence. It is **INVALID / EXTERNAL INTERRUPTION**, not a model or harness failure, and is excluded from all scoring, timing, and usage aggregates.
- Flash plot and all debugging attempts were not launched in this run.

The missing attempts were collected in the separate continuation run `tier-b-controlled-003`; no valid attempt was rerun.
