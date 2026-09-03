# Named local vLLM routes

Named local or shared vLLM routes are ordinary Ekalavya resolution targets.
They are not separate public executables.

## Configuration

Keep route definitions and credential references in the user-owned local
configuration. The public example is
`provider_templates/vllm.toml.example`; it contains no credentials. Inspect
availability with:

```bash
eka config --json
eka status --primary <identity>
eka status --live --primary <identity>
eka models --json
```

Normal status is network-free. `--live` is explicit GET-only observability;
it must not invoke inference or expose tokens. Missing credentials, invalid
configuration, unavailable endpoints, and resource limits remain distinct
states.

## Execution

Use the generic run interface with the configured route selector:

```bash
eka run vllm:<route> --provider vllm --family openai-compatible \
  --model <provider-model-id> --harness vllm \
  --workspace /absolute/scoped-workspace --prompt-file /absolute/task.md \
  --timeout 60
```

The route keeps its configured named identity, local default and maximum
token budget, concurrency/shared-compute policy, credential reference, and
failure/retention semantics. Ekalavya never invents a route or silently
switches to another one. Unsupported selectors fail before inference.

## Safety

Use a disposable workspace and bounded prompt. The adapter closes stdin,
enforces scope and timeout/process cleanup, records retained response
metadata, and leaves machine/server/GPU policy unchanged. Provider-reported,
calculated, API-equivalent, and unavailable costs remain separate.
