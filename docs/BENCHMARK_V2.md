# Benchmark V2

Benchmark V2 adds deterministic synthetic task generation and controller-side
evaluation for multi-file coding work. The public package is under
`benchmark/v2`; it does not copy evaluator code, seeds, expected patches, or
parent-repository files into a candidate workspace.

The initial coding families are configuration precedence, cache invalidation,
retry/idempotency, time-series leakage, state transitions, compatible
refactoring, and diagnostic artifacts. R1–R3 are fixed-rubric scientific
reasoning cases. `python -m benchmark.v2.runner check` is the no-inference gate:
it checks intentionally broken workspaces, private reference repairs,
reproducibility, and evaluator separation before any candidate is run.

Scores are correctness-first (0–100 from hidden functional checks) with public
tests, invariants, API compatibility, scope, telemetry, and latency reported
separately. `benchmark.v2.telemetry` parses provider-shaped JSON/JSONL traces
and leaves unavailable values null; it reports tool-schema errors, argument
errors, tool failures, and recovery independently.

Seeds and generated run manifests belong in private state. The generator is
deterministic for schema version plus seed, while candidate instructions remain
generic and do not reveal evaluator implementation.
