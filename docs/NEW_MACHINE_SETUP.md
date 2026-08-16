# New-machine setup

Canonical procedure to reproduce this repository's delegation environment on
a new Ubuntu/Linux workstation — including a university-managed laptop where
you don't control system packages the same way. Written so you can hand this
whole document to a fresh Codex or Claude Code session and say "follow this
and set my machine up" — see [SETUP_HANDOFF.md](SETUP_HANDOFF.md) for that
agent's short entry point.

Cloning this **public** repository never gives you: API keys, login
sessions, provider account balances, provider authentication, your
personal `delegate-config` availability preferences, or runtime logs. All of
those are machine-local and are either recreated fresh (config, logs) or
must be supplied by you (keys, authentication) — see "What does NOT need to
be copied" at the end.

Do not `chmod` this repository's working directory as part of installation —
none of the steps below need it, and blocking your own execute permission on
a directory your shell is rooted in can lock an agent out mid-task; see
[USER_INSTALLATION.md](USER_INSTALLATION.md#testing-portability-safely-and-a-hazard-to-avoid).

## 1. OS prerequisites

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv pipx libsecret-tools gnome-keyring bubblewrap
```

`libsecret-tools` provides `secret-tool` (login-keyring credential storage).
`bubblewrap` (`bwrap`) is what `codex exec`'s sandbox depends on — verify it
actually works in your shell in step 11 before spending anything.

If you don't have `sudo` on this machine (a locked-down university image),
ask IT for these specific packages, or use a per-user Python install
(`pip install --user pipx`) where policy allows it — the rest of this
procedure otherwise doesn't need elevated privileges.

## 2. pipx setup

```bash
python3 -m pip install --user pipx
python3 -m pipx ensurepath
```

Open a new shell afterward so `~/.local/bin` is on `PATH`.

## 3. Install the global delegation runtime

```bash
git clone <this repository's URL>
cd agent-delegation-benchmark
scripts/install-user-delegation.sh
```

This runs the test suite and no-model preflight, `pipx install`s the
package (producing `ask-flash`, `ask-haiku`, `ask-sonnet`,
`ask-deepseek-pro`, `ask-deepseek-flash`, `ask-minimax-m3`,
`delegate-status`, `delegate-config`), creates a default config only if one
doesn't already exist, and installs the delegation skill. No provider
authentication, no model calls. See
[USER_INSTALLATION.md](USER_INSTALLATION.md) for the full architecture.

## 4. Provider CLI prerequisites

Install Codex CLI, Claude Code, and (if you use it) the Antigravity/Gemini
frontend `agy`, per their own current official installation instructions —
this repository does not vendor or install them. Confirm each is on `PATH`:

```bash
command -v codex && codex --version
command -v claude && claude --version
command -v agy && agy --version   # if you use Antigravity
```

## 5. Normal Claude/Codex/Antigravity authentication

Authenticate each CLI through its normal subscription/account mechanism
(`codex login`, `claude` interactive login, `agy`'s own auth flow). This is
entirely outside this repository and outside PAYG credential handling below
— do not conflate the two. Never paste a session token or API key into a
shell command that gets logged; use each CLI's own interactive login.

## 6. DeepSeek/MiniMax PAYG provider bootstrap

Optional — only if you want the experimental PAYG routes at all. Everything
in this step is non-secret and source-controlled in `provider_templates/`:

```bash
scripts/setup-payg-providers.sh
```

This installs (see step 8 below for exactly what, and
[PAYG_DELEGATES.md](PAYG_DELEGATES.md) for the full design): the two Codex
model catalogs, the two Codex provider profiles (with the catalog path
rendered for *this* machine's `$CODEX_HOME`), and the four launcher scripts
(`codex-deepseek`, `codex-minimax`, `claude-deepseek`, `claude-minimax`) to
`~/.local/bin`. It refuses to overwrite a conflicting existing file at any
of its target paths rather than clobbering something you already have —
move the conflicting file aside yourself and re-run if that happens.

## 7. Login-keyring setup

The script above never touches a key. If it reports a provider's keyring
entry is missing, store it yourself, interactively (this prompts on your
terminal and is never captured in shell history or a log):

```bash
secret-tool store --label="DeepSeek API key" service ai-coding-provider provider deepseek
secret-tool store --label="MiniMax API key" service ai-coding-provider provider minimax
```

On a headless/SSH session without a graphical login keyring already
unlocked, you may need `dbus-run-session -- bash` (or your distro's
equivalent) first — consult your distribution's keyring documentation if
`secret-tool store`/`lookup` fails with a D-Bus or "no such secret
collection" error.

## 8. What "safe profile/catalog/launcher installation" means here

`scripts/setup-payg-providers.sh` (step 6) installs exactly these files,
all sourced from `provider_templates/` in this repository, never generated
or guessed:

| Installed to | From template |
|---|---|
| `$CODEX_HOME/deepseek.config.toml` | `provider_templates/codex/deepseek.config.toml.template` (path rendered) |
| `$CODEX_HOME/minimax.config.toml` | `provider_templates/codex/minimax.config.toml.template` (path rendered) |
| `$CODEX_HOME/model-catalogs/deepseek-v4.json` | `provider_templates/codex/model-catalogs/deepseek-v4.json` (verbatim) |
| `$CODEX_HOME/model-catalogs/minimax-m3.json` | `provider_templates/codex/model-catalogs/minimax-m3.json` (verbatim) |
| `~/.local/bin/codex-deepseek` (mode 700) | `provider_templates/launchers/codex-deepseek` (verbatim) |
| `~/.local/bin/codex-minimax` (mode 700) | `provider_templates/launchers/codex-minimax` (verbatim) |
| `~/.local/bin/claude-deepseek` (mode 700) | `provider_templates/launchers/claude-deepseek` (verbatim) |
| `~/.local/bin/claude-minimax` (mode 700) | `provider_templates/launchers/claude-minimax` (verbatim) |

No template contains a key, a personal username, or a hardcoded home path —
the only machine-specific value is `$CODEX_HOME`, substituted at install
time. Do not hand-edit an installed file to "fix" something; edit the
template in this repository and re-run the script instead, so the next
machine gets the fix too.

## 9. No-model validation

```bash
python -m unittest discover -s tests -q
python -m benchmark.runner check
python -m delegation.preflight
```

All three must pass before anything below. None makes a model call.

## 10. `delegate-status` validation

```bash
delegate-status --primary claude-code
```

Confirm all 8 routes appear, with `deepseek-pro`/`deepseek-flash`/
`minimax-m3` reported `payg`/`experimental` and `disabled` (reason
`experimental PAYG; benchmark pending`) unless you've deliberately enabled
them via `delegate-config` — see step 13.

## 11. Bubblewrap/user-namespace validation

**Do this before spending anything on a PAYG route or a Codex/DeepSeek/
MiniMax benchmark run.** `codex exec --sandbox <mode>` depends on
bubblewrap being able to set up its own sandbox from your shell:

```bash
bwrap --unshare-net --dev /dev --ro-bind / / /bin/true
```

If this fails (a common failure looks like `bwrap: loopback: Failed
RTM_NEWADDR: Operation not permitted`), you are in a shell nested inside
another sandbox without the namespace capabilities bubblewrap needs — this
project hit exactly that inside a Claude Code session; see
[PAYG_DELEGATES.md](PAYG_DELEGATES.md#smoke-test-evidence). It blocks
*every* `codex exec` invocation identically, regardless of provider — this
is not specific to DeepSeek/MiniMax. Retry from an ordinary terminal/SSH
session rather than a nested agent sandbox.

## 12. Optional tiny read-only smoke call

Only after step 11 succeeds, and only if you want to confirm a route
actually reaches its provider (this spends real PAYG money — one call):

```bash
mkdir -p /tmp/payg-smoke && cd /tmp/payg-smoke
echo '{"mode": "read-only"}' > .delegation-scope.json
echo 'print(2 + 2)' > check.py
ask-deepseek-flash --workspace /tmp/payg-smoke --prompt "What does check.py print? Answer in one line." --primary claude-code --timeout 60
```

## 13. Config TUI usage

```bash
delegate-config           # interactive checkbox screen, from a terminal
delegate-config list      # non-interactive, scriptable
delegate-config enable-provider deepseek
delegate-config enable deepseek-pro
```

PAYG rows show a `PAYG · experimental` tag distinguishing them from the
subscription/quota-based rows. See
[DELEGATE_CONFIGURATION.md](DELEGATE_CONFIGURATION.md).

## 14. Update procedure

```bash
git pull
scripts/install-user-delegation.sh      # idempotent; never touches your config
scripts/setup-payg-providers.sh         # idempotent; refuses on conflict
```

## 15. Uninstall procedure

```bash
scripts/install-user-delegation.sh --uninstall
```

Removes the pipx install and the skill files it created; preserves your
config and logs. For the PAYG provider files, remove them yourself (this
project doesn't script deleting files it doesn't own the full lifecycle
of): `$CODEX_HOME/{deepseek,minimax}.config.toml`,
`$CODEX_HOME/model-catalogs/{deepseek-v4,minimax-m3}.json`, and the four
`~/.local/bin/{codex,claude}-{deepseek,minimax}` launchers. Remove the
keyring entries with `secret-tool clear service ai-coding-provider provider
deepseek` (and `minimax`) if you want those gone too.

## 16. What does NOT need to be copied between machines

- API keys (DeepSeek, MiniMax, or any provider's) — stored only in each
  machine's own login keyring/CLI auth state.
- Login sessions / provider authentication for Codex, Claude, Antigravity.
- Provider account balances — never queried or stored by this project.
- Your `~/.config/agent-delegation/config.toml` availability preferences —
  each machine gets its own default (PAYG routes disabled) and you
  configure it independently per machine.
- Runtime logs (`~/.local/state/agent-delegation/delegate_runs/`,
  `runs/` benchmark evidence you generate locally).

Everything else needed to reproduce the setup is in this repository.
