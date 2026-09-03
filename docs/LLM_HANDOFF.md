# Agent handoff: Ekalavya

Ekalavya is the supported external delegation control plane. The primary
agent owns routing, context bounds, timeout choice, verification, and final
correctness.

Start with:

```bash
eka status --primary <identity>
eka profiles
eka models
eka history
```

Use `eka run <profile>` to select a configured profile default. Explicit
runtime selection is available with `--provider`, `--family`, `--model`,
`--reasoning`, and `--harness` when the backend exposes those values. Invalid
values fail before inference. There is no silent provider/model failover.

Codex/OpenAI, Claude/Anthropic, and Gemini work should use their native agent
facilities for same-provider work. Ekalavya reports
`same-provider-native-required` when an external call would violate that
rule.

Use a disposable scoped workspace, bounded context, and a declared timeout.
Read stdout and retained response evidence, then verify the result. Preserve
the first outcome and do not blindly retry. Respect shared concurrency and
local resource policy.

Persistent configuration is user-owned. Read it and respect it; do not change
defaults or availability permanently without explicit instruction. Ledger
records preserve requested intent, resolved identity, telemetry, and separate
actual/calculated/API-equivalent cost fields. Missing values remain null.
