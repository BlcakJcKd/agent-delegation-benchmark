# Claude Code orchestration

Claude Code owns its native Claude subagents. Ekalavya is the single
supported interface for an explicitly requested external provider call.

Before a call:

```bash
eka status --primary claude-code
eka profiles
eka models
```

Use `eka run <profile>` with a disposable workspace, bounded prompt file, and
explicit timeout. Select `--provider`, `--family`, `--model`, `--reasoning`,
or `--harness` only when the resolved backend advertises the requested value.
The resolver rejects unsupported values before inference and records the
requested/resolved identity.

Same-provider Claude work belongs to native Claude facilities. Ekalavya
returns `same-provider-native-required` for an external Claude-to-Claude
attempt. The primary must verify retained response evidence and reconcile any
disagreement before accepting the result.

Do not alter persistent configuration, provider defaults, shared resource
limits, or machine policy merely to satisfy a task. Use `eka config` only for
an explicitly authorized user-owned availability change. `eka doctor` is the
stable health check; `eka status --live` is an explicit GET-only resource
observation.
