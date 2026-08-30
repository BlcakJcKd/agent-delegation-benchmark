# Shared OpenAI-compatible vLLM delegates

The runtime includes a generic, direct HTTP adapter for named providers that
expose the OpenAI Chat Completions API. It is intended for bounded consultation
work, not as an automatic replacement for any existing route and not as a
coding-agent harness.

## Machine-local configuration

Copy `provider_templates/vllm.toml.example` to
`$XDG_CONFIG_HOME/agent-delegation/vllm.toml` (normally
`~/.config/agent-delegation/vllm.toml`) and edit it locally. The file is not
part of the public runtime state and must never be committed when it contains
private infrastructure.

Each named provider supplies a model, an OpenAI-compatible base URL, and a
credential reference. Credentials are resolved only at request time from
`env:VARIABLE` or from the Ubuntu login keyring using `secret-tool lookup`.
The key value is never written to an evidence record, issue record, exception,
or diagnostic stream. This project never uses `secret-tool search`.

## Bounded invocation

```text
ask-vllm <named-route> --workspace /absolute/scoped-copy \
  --prompt-file /absolute/minimal-task.md
```

The adapter makes one POST to `<base_url>/chat/completions`, sends only one
user message, defaults `chat_template_kwargs.enable_thinking` to `false`, and
enforces the configured local completion cap. New configurations use
`default_max_tokens` for the normal request budget and `max_tokens_cap` for the
caller-side ceiling; neither is a statement of the remote server or model
maximum. Legacy `max_tokens = N` maps safely to both values `N`. `--thinking`
is an explicit override; `--no-thinking` makes the default explicit. The
default timeout is 300 seconds.

The machine-local `flock` lock allows at most one shared vLLM request from the
machine at a time. It is acquired non-blocking, so a second session fails
clearly instead of adding a queue or a parallel fan-out. Kernel lock release
means a crashed process does not hold the lock indefinitely. There is no
automatic retry, speculative request, nested delegation, provider fallback,
or silent cloud substitution.

The normal delegation contract is preserved: textual response on stdout,
diagnostics and evidence summary on stderr, exit 124 plus `timed_out: true`
for a genuine timeout, and explicit failure categories for authentication,
API compatibility, rate limiting, server, connection, malformed-response,
empty-response, refusal, and concurrency failures.
The response text is held in memory long enough to replay it on stdout and is
not written to the evidence directory.

If a caller requests more than the configured local cap, validation fails
before credential lookup, the HTTP call, retry, or issue-log append. The error
names the requested value and says `local route cap`; it must not be read as a
remote server capability report.

## Local reliability records

Failed and incomplete requests append one redacted JSON object to
`$XDG_STATE_HOME/agent-delegation/vllm_issues.jsonl` with mode `0600` (normally
`~/.local/state/agent-delegation/vllm_issues.jsonl`). Successful requests are
represented by their normal `delegate_runs/<run>/execution.json` audit record;
they do not create an issue entry. Existing historical success entries in the
compatibility-named file are retained and are not rewritten or deleted.
Issue records contain timestamp,
local machine label, adapter, route/model, operation class, result state, HTTP
status, duration, timeout, thinking mode, sanitized error category, and the
fact that no retry/fallback occurred. It does not record the prompt, response,
authorization header, response body, or source files. Users can use the time,
route, and category from this file when reporting connection errors, repeated
failures, or poor responses to a service administrator.

## Availability control plane

`delegate-config` discovers named routes from `vllm.toml` and stores only their
enabled/disabled preference in `config.toml` under `[vllm.<route>]`. It displays
the configured model and shared-compute policy offline; it never queries
`/models` or the completion endpoint merely to render settings. `delegate-status`
reports enabled routes as available when their local schema is valid, and
separately reports disabled, invalid-configuration, or missing-credential-
reference states. It includes the configured local output cap without
contacting the server. It does not resolve credential values or perform a
health check in ordinary mode. `delegate-status --live` is an explicit,
GET-only observability mode: it samples `/load` and `/metrics` twice, never
uses inference or credentials, and reports conservative `IDLE`, `ACTIVE`,
`PRESSURED`, or `UNKNOWN` scheduler state. Live scheduler state is not GPU
utilization. The full Codex/Qwen harness, if present, is a separate local
coding-agent command and is not a delegation route.

## Codex harness compatibility

The direct adapter is separate from Codex's primary-model transport. Codex
custom providers require the Responses wire API; compatibility therefore
depends on the target vLLM exposing a sufficiently OpenAI-compatible
`/v1/responses` implementation. Audit the installed Codex version and target
server together before occasional harness use. Do not add a proxy solely to
force compatibility.
