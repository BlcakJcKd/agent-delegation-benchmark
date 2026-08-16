# Delegation failure modes

Operational reference for how `delegation/core.py` behaves when something
goes wrong. Same principle as the benchmark itself (see
[AGENT_BENCHMARK_HANDBOOK.md](AGENT_BENCHMARK_HANDBOOK.md) §7): **an
infrastructure failure is not a model failure.** None of the classes below
should be read as evidence about Flash, Haiku, or Sonnet's capability.

Validated in [`tests/test_delegation_failure_modes.py`](../tests/test_delegation_failure_modes.py),
[`test_delegation.py`](../tests/test_delegation.py), and
[`test_wrapper_scripts.py`](../tests/test_wrapper_scripts.py); see
[CLAUDE_CODE_SMOKE_TEST.md](CLAUDE_CODE_SMOKE_TEST.md) for the one live
clean-path run this failure-mode sweep follows up on.

The table below is about `delegation/core.py` consultation failures
specifically. For a *test-methodology* hazard encountered while verifying
the installed runtime's portability — a `chmod 000` self-lockout that is not
a delegation, pipx, Git, or installation failure — see
[USER_INSTALLATION.md](USER_INSTALLATION.md#testing-portability-safely-and-a-hazard-to-avoid).

| Failure class | Symptom | Classification | Expected wrapper behaviour | Retry policy | Model performance inferable? | Operator action |
|---|---|---|---|---|---|---|
| Invalid scope (missing marker, malformed JSON, wrong/absent `mode`, present symlink) | `run_consultation` raises `ValueError` before any subprocess starts | Infrastructure / operator setup failure | `_validate_scope` rejects synchronously; no subprocess, no log directory beyond the raise point, workspace untouched | None — fix the workspace and re-invoke | No | Correct the scoped workspace (add/repair `.delegation-scope.json`, remove symlinks) and retry manually |
| Recursive delegation | `run_consultation` raises `ValueError("recursive delegation rejected: ...")`, including for a malformed `AGENT_DELEGATION_DEPTH` | Policy / infrastructure rejection | `_check_recursion_guard` runs first, before delegate-name or scope validation; no subprocess launched | None — this is a hard stop, not a transient condition | No | Investigate why a delegated context tried to call an approved wrapper again; do not unset the marker to force through |
| Missing delegate executable | `run_consultation` raises `RuntimeError("delegate executable is unavailable: <name>")` | Infrastructure / environment failure | `shutil.which` checked after scope validation, before argv/log construction; no subprocess; no substitution of a different `DELEGATES` entry | None | No | Install/authenticate the missing CLI, or fix `PATH`; do not silently fall back to another model |
| Timeout | `subprocess.TimeoutExpired` caught; exit code recorded as `124`, `timed_out: true` in `execution.json` | Infrastructure failure (unless the task was genuinely too large for a reasonable timeout, which is an operator sizing decision, not a model score) | Python's `subprocess.run(..., timeout=...)` kills the child on timeout; `execution.json` and `stdout.txt`/`stderr.txt` (partial output, if any) are still written; workspace is never touched by this path | None automatic — `run_consultation` makes exactly one attempt; a human/primary may choose to re-invoke with a larger `--timeout` | No | Re-invoke manually with an adjusted timeout if the task genuinely needs more time; do not auto-retry in a loop |
| Non-zero delegate exit | `run_consultation` returns whatever `returncode` the delegate CLI produced; `cli.py` propagates it as the process exit code | Ambiguous by default — could be a CLI usage/auth/crash error (infrastructure) or the delegate's own reported failure. `core.py` does not classify this further | Exit code, stdout, and stderr are all logged verbatim in `execution.json`/`stdout.txt`/`stderr.txt` for the primary to inspect | None automatic | Only after the primary reads stdout/stderr and rules out an infrastructure cause (auth, flag rejection, crash) | Read the raw log before drawing any conclusion; do not treat a non-zero exit as a de facto model score |
| Malformed/unparseable provider output | Delegate exits 0 but `stdout.txt` is not the expected JSON/text shape | Not detected by `core.py` at all — it captures stdout as opaque text and performs no parsing or schema check | None specific; this is unchanged from the happy path | N/A | No — an unparseable response is evidence about output formatting/harness compatibility, not the delegate's reasoning quality | Treat the response as inconclusive per [CLAUDE_CODE_ORCHESTRATION.md](CLAUDE_CODE_ORCHESTRATION.md)'s verification rule: never act on a claim that can't even be read cleanly |
| Authentication failure | Delegate CLI exits non-zero with an auth-specific message in stdout/stderr | Model/account compatibility failure — mirrors the benchmark's own documented incident classification (`AGENT_BENCHMARK_HANDBOOK.md` §7, `MODEL/ACCOUNT COMPATIBILITY FAILURE`) | Indistinguishable at the `core.py` layer from any other non-zero exit; the primary must read stderr to recognize it as an auth issue | None automatic; no silent re-authentication or model substitution is attempted anywhere in this codebase | No | Re-authenticate the CLI out of band, then re-invoke manually |

## What this sweep validated (2026-08-16, no real delegate CLI invoked)

- **Invalid scope** — missing marker, malformed JSON, wrong `mode` value, and
  a non-object marker body all reject with a clear `ValueError` before any
  subprocess spawns, and leave the scoped workspace byte-identical.
- **Recursion rejection** — depth values `1`, `2`, `5`, and a malformed
  string all reject fail-closed with zero subprocess launches, both at the
  Python-API level and end-to-end through the real `bin/ask-flash` script.
- **Timeout** — a real (not mocked) `sleep 60` child process, invoked
  through the same `run_consultation` orchestration with `timeout_seconds=1`,
  is genuinely killed by `subprocess.run`'s timeout handling: confirmed with
  `pgrep` finding no leftover process afterward, exit code `124`, single
  attempt only, scoped workspace unchanged.
- **Missing executable** — simulated via patching `shutil.which` for the
  `flash`/`agy` lookup only (the real installed `agy` binary was never
  touched, renamed, or uninstalled); confirms a clear `RuntimeError`, zero
  subprocess launches, and no fallback probing of any other `DELEGATES`
  entry.

Zero model/paid calls were made for this validation; every case above is
reachable and provable with mocks or a harmless local `sleep`.

## Zero-model-call discovery subprocesses must not inherit caller stdin

`delegation/preflight.py` and `benchmark/preflight.py` (the `check`/
`run_preflight` paths behind `python -m delegation.preflight` and
`python -m benchmark.runner preflight`/`check`) each run short-lived
discovery probes — `<cli> --version`, `<cli> --help` / `exec --help`, and
`agy models` — that are documented and relied upon as making *no* model
call. Both funnel every such probe through a private `_capture()` helper
that wrapped `subprocess.run(command, text=True, capture_output=True)`
with no `stdin` argument, so the child inherited whichever file descriptor
the calling process's stdin happened to be.

That is only safe if nothing upstream ever pipes real content into that
stdin. It is not: `agy` treats non-empty piped stdin as an inline
conversational prompt regardless of subcommand, so `agy models` run with
piped text reaching it makes a real (if not PAYG-billed) model call
instead of the metadata listing the check expects — silently converting a
"no model invocation" step into one, and doing so before any of this
project's explicit paid-run confirmation prompts are ever reached. This was
found by hand: running a benchmark launcher script under a piped stdin
(anything upstream of its confirmation `read`, including the confirmation
answer itself, sits in the same inherited pipe) caused `agy` to reply
conversationally instead of returning its model list.

Fix: `_capture()` in both modules now passes `stdin=subprocess.DEVNULL`
explicitly, so every discovery/version/help probe always sees a closed
stdin (immediate EOF) regardless of what the parent process's stdin is
connected to. Covered by
[`tests/test_preflight_stdin_isolation.py`](../tests/test_preflight_stdin_isolation.py),
which mocks `subprocess.run` throughout (the real `agy`/`claude`/
`codex-deepseek` binaries are never invoked) and asserts `stdin=DEVNULL` on
every discovery call made by `delegation.preflight.check()` and
`benchmark.preflight.run_preflight()`, including the specific `agy models`
call.

The general lesson: any subprocess a "no model invocation" code path
spawns must have its stdin explicitly closed or redirected, not merely
left unset — "unset" means "inherited," and an inherited stdin can carry
prompt-bearing content the check's author never intended it to see. The
delegate-invoking path in `delegation/core.py::run_consultation` is exempt
from this concern by construction: the prompt there is always the final
argv element, never delivered over stdin, so there is nothing for an
inherited stdin to be misread as.
