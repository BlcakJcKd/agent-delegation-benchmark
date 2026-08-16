# LLM handoff

Entry point for a new agent picking up this repository — ChatGPT, Claude Web,
Claude Code, Codex, or another capable agent.

## Read first

1. [`README.md`](../README.md)
2. [`docs/AGENT_BENCHMARK_HANDBOOK.md`](AGENT_BENCHMARK_HANDBOOK.md)
3. [`docs/DELEGATION_POLICY.md`](DELEGATION_POLICY.md)

If you are Claude Code specifically, also read
[`docs/CLAUDE_CODE_ORCHESTRATION.md`](CLAUDE_CODE_ORCHESTRATION.md).

## Current operational defaults

- Delegation is allowed unless the user prohibits it.
- The primary agent chooses whether and which delegate to use.
- A primary runtime's own native subagent facility may be preferred over an
  external CLI delegate when one is genuinely useful.
- Gemini 3.7 Flash Medium (via `bin/ask-flash`) is spare/high-quota capacity,
  not a mandatory step.
- The primary agent owns verification and integration of anything a delegate
  returns; a delegate's claim is not itself evidence.
- No recursive approved-wrapper delegation: `primary -> delegate` is allowed,
  `delegate -> another delegate` is rejected by the wrapper.
- External consultation is read-only by default; no wrapper here grants a
  delegate write access.

This is intentionally not a restatement of the full handbook or policy —
read those documents for the reasoning, evidence, and limitations behind
these defaults.
