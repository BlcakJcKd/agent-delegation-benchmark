# Claude Code orchestration

How Claude Code acts as primary owner of this repository and, when useful,
consults Gemini 3.7 Flash through the approved `bin/ask-flash` wrapper. Read
[DELEGATION_POLICY.md](DELEGATION_POLICY.md) first; this document is the
Claude-Code-specific operational supplement, not a replacement for it.

## Claude Code as primary owner

Claude Code can run every phase of this repository's work directly: reading
code, running tests, editing files, and deciding what changes to make. It
owns architecture, implementation, validation, integration, and final
conclusions. Nothing in `delegation/` assumes a Codex parent process or
Codex-specific environment; the wrappers are plain subprocess calls invoked
the same way regardless of which agent's `Bash` tool runs them.

This applies whether Claude Code is working inside this repository or in an
entirely different project: once installed (see
[USER_INSTALLATION.md](USER_INSTALLATION.md)), `ask-flash`,
`delegate-status`, and `delegate-config` are ordinary commands on `PATH`,
independent of this checkout.

## Gemini Flash is optional spare capacity, not mandatory

Flash is a cheap, high-quota, read-only consultation delegate — not a
required step. Do not mechanically consult it on every task.

## When delegation is worth it

Delegate to Flash only when one of these holds:

- **Verification is materially cheaper than generation.** Flash can scan a
  workspace and report file:line evidence faster than re-deriving it, and
  its claims are cheap to check against the real files.
- **Independent reasoning/critique adds diversity.** A second, differently
  biased read of the same evidence is useful before committing to a
  conclusion.

If neither applies, do the work directly — the context-preparation and
verification overhead is not free.

## Preparing a scoped workspace

Flash never receives more than it needs and never receives write access.

1. Create a dedicated directory containing only files safe to disclose. Do
   not include credentials, `private_admin/`, `blind_map.json`, or another
   task's evidence.
2. Ensure it contains no symlinks (`_validate_scope` in `delegation/core.py`
   rejects any).
3. Add `.delegation-scope.json`:

   ```json
   {"mode": "read-only"}
   ```

   This is an operator assertion, not a security boundary — Flash still runs
   in `agy --mode plan --sandbox`, which is a product-level control, not a
   cryptographic one.

## Check what's eligible first

```bash
delegate-status --primary claude-code
```

Zero model calls. Shows, per route, its configured state (with any reason
the user set), whether it's `external`, `same-provider`/`native-only`, or
`disabled`, and whether the wrapper's executable is actually on PATH. Add
`--json` for machine-readable output. Respect a disabled route or provider —
it's user-owned configuration (see
[DELEGATE_CONFIGURATION.md](DELEGATE_CONFIGURATION.md)); read and report it,
don't work around it or change it on your own judgement.

## Invoking ask-flash

```bash
ask-flash --workspace /absolute/scoped-copy \
  --prompt-file /absolute/consultation-task.md --timeout 300 \
  --caller claude-code --primary claude-code
```

(`bin/ask-flash` inside this checkout is equivalent for development; the
installed `ask-flash` command works identically from any directory, in any
project, once installed.)

`--caller` is optional, provenance-only metadata (falls back to
`$AGENT_DELEGATION_CALLER`, then `"unknown"`). It is recorded in
`execution.json` for audit purposes and never used to make a safety
decision. `--primary` is a separate, distinct mechanism — see "Two distinct
guards" below.

## Inspecting logs and results

Each call writes a timestamped directory under `delegate_runs/` (or
`--log-root`), outside the consulted workspace:

- `prompt.md` — exact prompt sent
- `stdout.txt` / `stderr.txt` — raw CLI output
- `execution.json` — delegate, caller, requested model/effort, workspace,
  timing, exit code, redacted argv, and whether the call timed out

Read these with the `Read` tool like any other file; nothing about them
requires special handling.

## Verifying findings

Treat every claim Flash returns as a hypothesis, not a fact:

1. Read the cited file:line evidence directly.
2. Re-run any verification command it proposes, if safe to do so.
3. Only act on a claim once you have independently confirmed it against the
   real files or test output.

## Two distinct guards

**Recursion-depth guard.** `primary -> delegate` is allowed.
`delegate -> ask-flash/ask-haiku/ask-sonnet` is rejected by the wrapper
itself: `run_consultation` checks the inherited `AGENT_DELEGATION_DEPTH`
environment marker and refuses to proceed (no subprocess is launched) if it
is already present and >= 1, including a malformed value. Every spawned
delegate's environment has `AGENT_DELEGATION_DEPTH=1` set explicitly, so a
delegate that tried to call an approved wrapper again would be rejected.
This only protects the approved wrappers in `delegation/`; it cannot stop a
delegate from invoking some other installed CLI directly if its own sandbox
permits that.

**Self-provider guard.** A declared `--primary` cannot externally call its
own provider: e.g. `ask-haiku --primary claude-code` is rejected before
launching anything, because same-provider work should go through Claude's
own native subagent capability, not a recursive-feeling external hop.
`delegate-status --primary claude-code` shows this as `route_type:
same-provider`, `effective: native-only`. Unlike the recursion guard, this
is based on a caller-declared value, not an inherited environment marker —
it is a routing/policy nudge, not a security boundary, and it is only
enforced when `--primary` is actually given (an absent value is unenforced,
never assumed). The Python runtime cannot detect or prevent a host from
using its own native agent feature; it can only refuse to be misused as a
same-provider external hop. `AGENT_DELEGATION_DEPTH` and `--primary` are
independent — either can reject a call regardless of the other's state.

## Minimal example

```text
Claude Code (primary)
  -> delegate-status --primary claude-code (zero model calls; check eligibility)
  -> prepare scoped copy (no symlinks, .delegation-scope.json present)
  -> ask-flash --workspace <scoped-copy> --prompt-file <task.md> --caller claude-code --primary claude-code
  -> inspect <state-log-dir>/delegate_runs/<timestamp>-flash-*/execution.json + stdout.txt
  -> independently verify every cited file:line claim
  -> decide whether to act, and act directly (Flash has no write access)
```

## Current limitations

- No implementation/write delegation exists yet; only read-only consultation.
- The scope marker is an operator assertion, not enforced isolation; prepare
  the workspace carefully.
- Claude's own CLI has no Codex-equivalent hard workspace-read sandbox; its
  CWD and restricted tool set are operational controls, not a filesystem
  containment guarantee.
- The recursion guard is environment-based; it protects the approved
  wrappers, not arbitrary CLI invocation by a delegate.
- The self-provider guard only applies when `--primary` is declared, and
  only prevents this runtime being misused as a same-provider external hop
  — it cannot detect or invoke a host's native agent feature itself.
- Quota/usage availability is user-managed in this version; nothing here
  auto-disables a route by threshold. See
  [DELEGATE_CONFIGURATION.md](DELEGATE_CONFIGURATION.md).
