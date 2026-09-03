# Ekalavya failure modes

Failures are explicit evidence, not permission for hidden failover.

Before execution, `eka status`, `eka profiles`, and `eka models` can reveal
availability and resolution problems without inference. Unsupported provider,
family, model, reasoning, or harness values fail locally. A same-provider
external request returns `same-provider-native-required`.

During execution, the adapter distinguishes missing executables, invalid
configuration, unavailable routes, malformed tool calls, timeout, process
cleanup, non-zero exits, empty responses, and retained-response failures. A
terminal or tool yield is not itself a timeout. The first attempt is retained;
retries are not automatic.

Every attempt uses a declared disposable workspace. Parent escape, symlink
escape, recursion, stdin, and scope checks are enforced before provider work.
The result is accepted only after stdout, retained response metadata, and the
workspace contract are verified.

Telemetry fields are nullable. Missing request, token, latency, tool, or cost
evidence must not be interpreted as zero. Ledger integrity and evidence hashes
can be checked with `eka doctor` and `eka history --json`.
