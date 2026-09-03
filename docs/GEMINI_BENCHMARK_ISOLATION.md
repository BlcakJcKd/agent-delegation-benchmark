# Gemini Benchmark Isolation Gate

Benchmark V2 candidate execution requires a disposable workspace, blocked
parent/repository access, blocked arbitrary network access from candidate
tools, and an independently controllable tool-execution boundary. Provider
transport must remain available to the harness; putting the whole provider
client in a zero-network namespace is not a valid substitute.

The current Linux test environment has an unprivileged `bwrap` 0.9.0
installation. A standalone
synthetic bwrap fixture can contain a tool process with a workspace-only
filesystem, parent/sibling path denial, and an unshared network namespace.
That fixture is not a Gemini harness: it becomes relevant only when the
selected provider adapter can attach it at the genuine candidate-tool
subprocess boundary.

AGY 1.1.25 does not document or expose that boundary. Its `--sandbox` option
does not provide an Ekalavya-controlled child-tool executor while AGY's
provider transport remains connected. Therefore AGY remains suitable for
ordinary delegation but invalid for hidden Benchmark V2 execution. The
experiment controller records this as an explicit preflight failure and does
not start benchmark attempts.

The installed Gemini CLI 0.55.1 has a separate container sandbox design, but
its Linux implementation requires Docker or Podman. Neither is available on
this machine, so it is not a qualifying alternative here. OpenCode likewise
did not expose an exact Gemini candidate with a qualifying isolation contract;
the harness comparison is not performed.

The isolation preflight is zero-inference. Any future harness must pass the
synthetic filesystem, process, network, and provider-transport checks before a
single hidden-task candidate call is allowed.
