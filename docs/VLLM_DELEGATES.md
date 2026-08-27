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
enforces the configured completion cap. `--thinking` is an explicit override;
`--no-thinking` makes the default explicit. The default timeout is 300 seconds.

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

## Local reliability records

Every attempted request appends one redacted JSON object to
`$XDG_STATE_HOME/agent-delegation/vllm_issues.jsonl` with mode `0600` (normally
`~/.local/state/agent-delegation/vllm_issues.jsonl`). It records timestamp,
local machine label, adapter, route/model, operation class, result state, HTTP
status, duration, timeout, thinking mode, sanitized error category, and the
fact that no retry/fallback occurred. It does not record the prompt, response,
authorization header, response body, or source files. Users can use the time,
route, and category from this file when reporting connection errors, repeated
failures, or poor responses to a service administrator.

## Codex harness compatibility

The direct adapter is separate from Codex's primary-model transport. Codex
CLI versions that only support the Responses wire API cannot directly use a
Chat Completions-only vLLM endpoint. Do not add a proxy solely to force that
combination; audit the installed Codex version first and consider a compatible
coding-agent product separately.
