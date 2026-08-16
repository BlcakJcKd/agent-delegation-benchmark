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

## Invoking ask-flash

```bash
bin/ask-flash --workspace /absolute/scoped-copy \
  --prompt-file /absolute/consultation-task.md --timeout 300 \
  --caller claude-code
```

`--caller` is optional, provenance-only metadata (falls back to
`$AGENT_DELEGATION_CALLER`, then `"unknown"`). It is recorded in
`execution.json` for audit purposes and never used to make a safety
decision. `bin/ask-flash` resolves the `delegation` package relative to its
own location, so it works from any working directory, including one outside
this repository.

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

## Recursion rule

`primary -> delegate` is allowed. `delegate -> ask-flash/ask-haiku/ask-sonnet`
is rejected by the wrapper itself: `run_consultation` checks the inherited
`AGENT_DELEGATION_DEPTH` environment marker and refuses to proceed (no
subprocess is launched) if it is already present and >= 1, including a
malformed value. Every spawned delegate's environment has
`AGENT_DELEGATION_DEPTH=1` set explicitly, so a delegate that tried to call
an approved wrapper again would be rejected. This only protects the approved
wrappers in `delegation/`; it cannot stop a delegate from invoking some other
installed CLI directly if its own sandbox permits that.

## Minimal example

```text
Claude Code (primary)
  -> prepare scoped copy (no symlinks, .delegation-scope.json present)
  -> bin/ask-flash --workspace <scoped-copy> --prompt-file <task.md> --caller claude-code
  -> inspect delegate_runs/<timestamp>-flash-*/execution.json + stdout.txt
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
