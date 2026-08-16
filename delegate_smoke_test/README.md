# Delegate smoke-test workspace

Synthetic, non-sensitive scoped workspace for a single read-only Gemini 3.7
Flash consultation (see `docs/CLAUDE_CODE_SMOKE_TEST.md`). Not part of the
benchmark's `fixtures/`/`tasks/` suite; do not confuse with harness evidence.

`calc.py` has one deliberately seeded logic bug. `test_calc.py` fails because
of it. Do not modify any file in this directory.

Task for the delegate: identify (1) the likely cause, (2) exact file:line
evidence, (3) the smallest command to verify the fix, without making any
edit.
