# Claude Code -> Gemini Flash smoke test

One recorded, live delegate consultation validating that Claude Code can use
this repository's delegation infrastructure. This is a single data point, not
a general reliability claim.

- **Date:** 2026-08-16
- **Primary:** Claude Code, Sonnet 5, effort medium
- **Delegate:** Gemini 3.7 Flash Medium via `bin/ask-flash` (`agy --mode plan
  --sandbox --model gemini-3.7-flash-medium --effort medium`)
- **Caller metadata:** `claude-code` (recorded in `execution.json`, audit-only)

## Task

A tiny synthetic workspace at `delegate_smoke_test/` containing `calc.py`
(one seeded bug: `average` divides by `len(values) - 1` instead of
`len(values)`), `test_calc.py` (one deliberately failing assertion),
and a `README.md` giving task context. Flash was asked, read-only, to
identify the likely cause, exact file:line evidence, and the smallest
verification command — explicitly not to fix anything.

## Scope

`delegate_smoke_test/.delegation-scope.json` = `{"mode": "read-only"}`. No
symlinks. No credentials or benchmark private material present. Log root
(`delegate_runs/`) is outside the consulted workspace, per policy.

## Recursion guard

Active. `AGENT_DELEGATION_DEPTH` was unset in the primary's environment
(root invocation), so the call proceeded; the delegate subprocess was
launched with `AGENT_DELEGATION_DEPTH=1` in its environment
(`execution.json.child_delegation_depth: 1`), which would cause any nested
attempt to re-invoke an approved wrapper to be rejected before a subprocess
launched.

## Result

- **Wall time:** 10.84s (`execution.json.wall_seconds`); reported delegate
  duration 7.47s.
- **Exit code:** 0, not timed out.
- **Correctness:** correct. Flash cited `calc.py:4` (`total / (len(values) -
  1)`) as the bug, the exact expected fix (`total / len(values)`), the
  correct failing assertion (`test_calc.py:7-8`), and the correct smallest
  verification command (`python3 -m unittest test_calc.py` — this repo's
  convention is `python`, an equivalent form). It also flagged an accurate,
  unprompted edge-case uncertainty (empty-list division), rather than
  overclaiming.
- **Verification method:** independently re-read `calc.py` line 4, re-ran
  `python -m unittest test_calc -v` to reproduce the cited failure, and
  diffed SHA-256 checksums of every file in the scoped workspace before and
  after the call — no file changed.
- **Verification cost vs. generation cost:** verification was materially
  cheaper than the original investigation. Confirming Flash's three claims
  took one file read and one test run (a few seconds); Flash's own
  consultation took ~11 seconds wall time end to end. For a task this small
  the saving is modest in absolute terms, but the pattern (cheap file:line
  claims, cheap to check) is the one this delegate is suited for.
- **Workspace integrity:** confirmed unchanged (SHA-256 diff empty).
- **CLI/sandbox/permission issues:** none. The call completed cleanly on the
  first attempt; no retry was needed or used.

## Conclusion

Claude Code can invoke `bin/ask-flash` directly through its own Bash tool,
receive a correctly-scoped, read-only, single-subprocess-argument
consultation, and verify the result cheaply against real files. This one
successful run does not establish general reliability — it is a single
clean-path data point, with no adversarial input, no failure-mode coverage,
and a trivial task. A next step would be repeated runs, a harder task, and a
deliberately induced failure case (e.g. missing executable, malformed scope)
before treating this pathway as dependable for larger work.
