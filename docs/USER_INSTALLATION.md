# User-level installation

How to install delegation as commands usable from any project, not just this
repository — and what stays true after you do.

## Architecture

```
agent-delegation-benchmark repository        (source / development / evidence)
    |
    | scripts/install-user-delegation.sh
    |
    +--> installed user-level Python runtime  (pipx venv, self-contained)
    |        provides: ask-flash, ask-haiku, ask-sonnet,
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
cd ~/Desktop/Side_Projects/agent-delegation-benchmark   # or wherever you cloned it
scripts/install-user-delegation.sh
```

This: runs the test suite and the no-model delegation preflight; installs
the package with `pipx install --force` (no sudo, no venv activation to
remember — pipx manages its own isolated venv and puts the five commands on
your `PATH`); creates a default config only if one doesn't already exist;
and installs/refreshes the skill. It makes no provider-authentication
changes and no model calls.

If a command reports `NOT ON PATH` at the end, run `pipx ensurepath` and
open a new shell.

### New-laptop checklist

1. Install `pipx` if you don't have it: `python3 -m pip install --user pipx
   && python3 -m pipx ensurepath`, then open a new shell.
2. Clone this repository.
3. Run `scripts/install-user-delegation.sh`.
4. Authenticate whichever CLIs you intend to use as delegates (`claude`,
   `agy`) the normal way — this installer never touches authentication.
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

## What's still true after install

- The pinned model each route resolves to (`flash` -> `gemini-3.7-flash-medium`,
  etc.) is fixed in code, not configurable — see
  [DELEGATE_CONFIGURATION.md](DELEGATE_CONFIGURATION.md).
- Recursion prevention and the self-provider guard are enforced by the
  installed code itself, not by the skill text — see
  [CLAUDE_CODE_ORCHESTRATION.md](CLAUDE_CODE_ORCHESTRATION.md).
- Read-only consultation remains the only supported delegation mode.
