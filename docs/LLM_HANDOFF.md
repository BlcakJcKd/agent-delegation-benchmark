# LLM handoff

Entry point for a new agent picking up this repository — ChatGPT, Claude Web,
Claude Code, Codex, or another capable agent.

## Read first

1. [`README.md`](../README.md)
2. [`docs/AGENT_BENCHMARK_HANDBOOK.md`](AGENT_BENCHMARK_HANDBOOK.md)
3. [`docs/DELEGATION_POLICY.md`](DELEGATION_POLICY.md)
4. [`docs/DELEGATE_CONFIGURATION.md`](DELEGATE_CONFIGURATION.md)

If you are Claude Code specifically, also read
[`docs/CLAUDE_CODE_ORCHESTRATION.md`](CLAUDE_CODE_ORCHESTRATION.md).

If delegation is already installed on this machine (check `command -v
delegate-status`), you do not need this repository at all to use it — see
[`docs/USER_INSTALLATION.md`](USER_INSTALLATION.md).

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
- A declared primary cannot externally call its own provider (the
  self-provider guard, distinct from recursion prevention) — use your own
  native agent capability for same-provider work instead.
- Check `delegate-status --primary <your-identity>` before delegating; it
  makes zero model calls and reports what's actually eligible.
- Availability config (`delegate-config`) is user-owned state: read and
  respect it, don't mutate it on your own judgement.
- External consultation is read-only by default; no wrapper here grants a
  delegate write access.

This is intentionally not a restatement of the full handbook or policy —
read those documents for the reasoning, evidence, and limitations behind
these defaults.
