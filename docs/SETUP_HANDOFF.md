# Setup handoff

A fresh coding agent on another machine should read this first, before
touching anything, when the human says something like "set up my delegation
environment by following the repository docs."

## Read next, in order

1. [NEW_MACHINE_SETUP.md](NEW_MACHINE_SETUP.md) — the actual procedure, 16
   ordered steps. Follow it; don't paraphrase it from memory.
2. [PAYG_DELEGATES.md](PAYG_DELEGATES.md) — only if the human wants the
   optional DeepSeek/MiniMax routes (`NEW_MACHINE_SETUP.md` step 6).
3. [VLLM_DELEGATES.md](VLLM_DELEGATES.md) — only if the human wants an
   optional machine-local named OpenAI-compatible vLLM route.
4. [DELEGATION_POLICY.md](DELEGATION_POLICY.md) and
   [DELEGATE_CONFIGURATION.md](DELEGATE_CONFIGURATION.md) — once the runtime
   is installed and you're about to actually delegate something.

## Ground rules for this task specifically

- **Inspect before modifying.** Read what already exists at a target path
  (`$CODEX_HOME/*.config.toml`, `~/.local/bin/*`,
  `~/.config/ekalavya/config.toml`) before writing to it.
  `scripts/setup-payg-providers.sh` already refuses to overwrite a
  conflicting file — respect that refusal, don't work around it by deleting
  or force-overwriting what's there. Ask the human instead.
- **Never reveal secrets.** No API key, ever, in output, a file you write,
  or a command you run that could be captured in a log or shell history.
  `secret-tool store` is interactive precisely so this can't happen — never
  script around that by passing a key as a command-line argument or
  environment variable literal.
- **Checking whether a keyring entry exists is not the same as reading it.**
  Use `secret-tool lookup service ai-coding-provider provider <name>
  >/dev/null 2>&1` and inspect only the exit status — this is the pattern
  `scripts/setup-payg-providers.sh` already uses. Never run `secret-tool
  search` (with or without `--all`) or `secret-tool lookup` without
  redirecting stdout away from your own output: `search` prints the secret
  value in plaintext by design once the collection is unlocked, and doing
  this once in an agent session put a live DeepSeek key straight into that
  session's transcript, forcing the key to be treated as compromised and
  rotated. Never capture a lookup's stdout into a shell variable either —
  redirect it to `/dev/null`, check `$?`, nothing more.
- **Do not redesign the established architecture.** The provider/transport
  distinction (`delegation.routing`), the disabled-by-default PAYG policy,
  the keyring-based credential retrieval, and the Codex provider-profile
  launcher pattern are all deliberate — see
  [PAYG_DELEGATES.md](PAYG_DELEGATES.md) for why. Reproduce them; don't
  invent a cleaner-looking alternative.
- **Reproduce rather than reinvent.** Every file `scripts/setup-payg-providers.sh`
  installs comes from `provider_templates/` in this repository, verbatim or
  with only `$CODEX_HOME` substituted. If something seems to need a change,
  change the template and re-run the script — don't hand-write a one-off
  file on this machine that the repository doesn't know about.
- **Validate each provider independently.** Don't assume DeepSeek working
  implies MiniMax works, or vice versa — they're separate keyring entries,
  separate profiles, separate launchers. Run the no-model checks
  (`NEW_MACHINE_SETUP.md` step 9-11) for both before considering either
  "done."
- **Stop on conflicting existing user configuration.** If a target file
  already exists with different content, or a keyring entry already exists,
  do not silently pick a side. Report what you found and ask.
- **No model calls, no spending, without explicit human approval.** Every
  step through `NEW_MACHINE_SETUP.md` step 11 (bubblewrap validation) is
  free. Step 12 (the smoke call) and any benchmark run cost real money —
  never run them as part of "just set my machine up" unless the human
  explicitly asks for that too.
