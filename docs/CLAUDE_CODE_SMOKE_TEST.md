# Claude Code smoke test

This document describes a small, non-benchmark integration check for the
Ekalavya control plane.

1. Create a disposable workspace outside any research repository.
2. Run `eka status --primary claude-code`, `eka profiles`, and `eka doctor`.
3. Prepare a synthetic prompt file and invoke one explicitly selected
   cross-provider profile with `eka run`.
4. Require a deterministic marker, read the retained response, and verify the
   ledger entry.

Do not use private research content, benchmark tasks, hidden evaluators, or
retries. Same-provider Claude work belongs to native Claude facilities and is
not an external smoke target.
