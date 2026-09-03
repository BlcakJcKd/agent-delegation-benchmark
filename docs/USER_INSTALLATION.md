# User-level installation

How to install delegation as commands usable from any project, not just this
repository — and what stays true after you do.

## Architecture

```
ekalavya-delegation repository               (source / development / evidence)
    |
    | scripts/install-user-delegation.sh
    |
    +--> installed user-level Python runtime  (pipx venv, self-contained)
    |        provides: ask-flash, ask-haiku, ask-sonnet, ask-terra, ask-luna,
    |                   ask-deepseek-pro, ask-deepseek-flash, ask-minimax-m3,
    |                   ask-vllm
    |                   (experimental PAYG, disabled by default -- see
    |                   PAYG_DELEGATES.md),
    |                   delegate-status, delegate-config
    |
    +--> user config                          ($XDG_CONFIG_HOME/agent-delegation/config.toml)
    |        persistent availability policy, owned by you
    |
    +--> global skill                          (~/.agents/skills/delegation/SKILL.md,
             agent discovery/judgement           linked for Claude Code at
             instructions only                   ~/.claude/skills/delegation)
```

After installation, working in Folium, Samsung, Mercatura, or any other
project needs **no filesystem access to this repository**. The installed
commands, your config, and the skill are all independent of where (or
whether) this checkout still exists — see "Why a copy, not a symlink" below
for the one place that would otherwise be tempting to get wrong.

The source repository remains the place development, tests, and the
skill/config *template* live. It stops being a runtime dependency the moment
installation finishes.

## Install

```bash
cd ~/Desktop/Side_Projects/ekalavya-delegation   # or wherever you cloned it
scripts/install-user-delegation.sh
```

This: runs the test suite and the no-model delegation preflight; installs
the package with `pipx install --force` (no sudo, no venv activation to
remember — pipx manages its own isolated venv and puts all eleven commands on
your `PATH`); creates a default config only if one doesn't already exist
(the three experimental PAYG routes come out disabled either way — see
[PAYG_DELEGATES.md](PAYG_DELEGATES.md)); and installs/refreshes the skill.
It makes no provider-authentication changes and no model calls.

If a command reports `NOT ON PATH` at the end, run `pipx ensurepath` and
open a new shell. The install currently exposes eleven commands, including
the optional `ask-vllm` entry point.

`ask-vllm` is installed with the same runtime but reads only the optional
machine-local named-provider file described in
[VLLM_DELEGATES.md](VLLM_DELEGATES.md). The installer never creates or changes
that file.

### New-laptop checklist

1. Install `pipx` if you don't have it: `python3 -m pip install --user pipx
   && python3 -m pipx ensurepath`, then open a new shell.
2. Clone this repository.
3. Run `scripts/install-user-delegation.sh`.
4. Authenticate whichever CLIs you intend to use as delegates (`codex`,
   `claude`, `agy`) the normal way — this installer never touches
   authentication. Terra/Luna use the normal OpenAI/Codex subscription path;
   they are external only for non-Codex primaries and native-only for Codex.
5. From any other directory, run `delegate-status --primary <your-identity>`
   to confirm the installed commands work independent of this checkout.

## Update / reinstall

Re-run the same command:

```bash
scripts/install-user-delegation.sh
```

It's idempotent: `pipx install --force` rebuilds the installed copy from
your current checkout, your config is left untouched if it already exists,
and the skill file is refreshed (safe — it's a file this installer owns).

## Uninstall

```bash
scripts/install-user-delegation.sh --uninstall
```

Removes the pipx install and the skill files this installer created. It
**does not** delete your config (`$XDG_CONFIG_HOME/agent-delegation/`) or
logs (`$XDG_STATE_HOME/agent-delegation/delegate_runs/`) — remove those
yourself if you want a full wipe.

## Why a copy, not a symlink, for the skill

The skill source template lives at `skills/delegation/SKILL.md` in this
repository. The installer **copies** it to
`~/.agents/skills/delegation/SKILL.md` rather than symlinking to the
checkout. A symlink back into this repo would quietly reintroduce the exact
dependency this whole effort removes: an agent in another project reading
its skill would need this checkout to still exist and be readable. The copy
is the one deliberate coupling point between source and installed state, and
it only exists at install/update time, not at skill-read time.

`~/.claude/skills/delegation` is a symlink to
`~/.agents/skills/delegation` — matching the existing convention already
used by this machine's other skills — which is fine, since neither endpoint
depends on this repository.

## Skill discovery

`~/.agents/skills/<name>/SKILL.md` is this machine's existing canonical
skill source location; other installed skills (`caveman`, `diagnose`, etc.)
already live there. Claude Code discovers skills via `~/.claude/skills/`,
where each entry is a symlink into `~/.agents/skills/` — the installer
follows that exact pattern for `delegation`.

This was verified by inspecting `~/.claude/skills/` directly; it was not
assumed to be identical across Codex or Antigravity/Gemini. Neither of those
was confirmed to auto-discover `~/.agents/skills/` on this machine as part
of this work. The installed **commands** do not depend on skill discovery
either way — `ask-flash`, `delegate-status`, etc. work whether or not a
given host surfaces the skill text automatically. If your Codex or Gemini
setup has its own supported user-level skill location, point it at
`~/.agents/skills/delegation/SKILL.md` (or check that product's current
documentation) rather than duplicating the file.

## Testing portability safely (and a hazard to avoid)

Normal installation and normal use require **no `chmod` operation at all** —
none of the install, update, or uninstall steps above touch permission bits
on this checkout. This section is only relevant if you want to go further
and independently *prove* the installed runtime has no residual dependency
on the source checkout.

**Do not use `chmod 000` on the active coding-agent working directory to
test source-checkout independence.** During this project's own portability
verification, that method was used and it worked for its immediate
purpose — `delegate-status`, `ask-flash --help`, `ask-haiku --help`,
`ask-sonnet --help`, and `delegate-config --help` all ran correctly from
`/tmp` with the repository fully inaccessible — but it also locked the
coding agent out of its own working directory: its Bash tool re-enters that
directory before running each subsequent command, so once the directory had
no execute permission, every following command (including the one meant to
restore permissions) failed immediately with no output. This is a
**test-method / troubleshooting hazard**, not a failure of the delegation
runtime, pipx, Git, or the installer — the installed commands behaved
exactly as intended throughout; only the *test rig* (an agent whose shell
session lives inside the directory being blocked) got stuck. No benchmark
evidence, config, logs, or repository content was lost or corrupted; the
directory's contents were never touched, only its permission bits.

Prefer one of these instead, none of which can lock anything out:

- Invoke the installed commands from `/tmp` or another ordinary directory
  (no permission changes needed — this alone proves cross-directory use).
- Run with `PYTHONPATH` cleared/unset, to confirm nothing falls back to a
  repo-relative import path.
- Test inside a separate, already-isolated environment (e.g. the pipx venv
  directly, or a container/VM) that has no copy of the source checkout at
  all.
- Copy the checkout to a disposable location, delete *that copy*, and
  confirm the installed commands are unaffected — deleting a disposable
  copy carries none of the lock-out risk of blocking the one your own
  session is rooted in.
- Mock or stub source-path access in a test (as this project's own
  `tests/test_wrapper_scripts.py` and `tests/test_entrypoints.py` do)
  rather than manipulating real filesystem permissions.

If a working directory is ever accidentally made inaccessible this way,
restore it to **whatever the normal mode is for that machine** — do not
assume or prescribe a universal value like `755` or `775`. On the machine
this incident happened on, `775` was correct only because it matched the
sibling directories already under `~/Desktop/Side_Projects/`; that's local
filesystem/umask policy on that one machine, not a requirement of this
project. Check a sibling directory's mode (`stat -c "%a" ../some-other-dir`)
or your system's default umask before picking a value. Note also that Git
does not preserve ordinary directory modes such as `755`/`775`/`000` — it
only tracks a file's executable bit, not directory permissions at all — so
a fresh clone of this repository is governed by your local filesystem's and
shell's umask defaults regardless of what any previous checkout's directory
mode was.

## What's still true after install

- The pinned model each route resolves to (`flash` -> `gemini-3.7-flash-medium`,
  etc.) is fixed in code, not configurable — see
  [DELEGATE_CONFIGURATION.md](DELEGATE_CONFIGURATION.md).
- Recursion prevention and the self-provider guard are enforced by the
  installed code itself, not by the skill text — see
  [CLAUDE_CODE_ORCHESTRATION.md](CLAUDE_CODE_ORCHESTRATION.md).
- Read-only consultation remains the only supported delegation mode.
