#!/usr/bin/env bash
# Install the delegation runtime as user-level, cross-project commands.
#
# What this does, in order:
#   1. no-model checks: the test suite and the no-model delegation preflight
#   2. `pipx install --force` the `delegation` package from this checkout,
#      producing ask-flash / ask-haiku / ask-sonnet / ask-deepseek-pro /
#      ask-deepseek-flash / ask-minimax-m3 (experimental PAYG, disabled by
#      default -- see docs/PAYG_DELEGATES.md) / delegate-status /
#      delegate-config as commands independent of this repo's location
#      after install (pipx builds and copies the package into its own venv)
#   3. create an initial XDG config.toml only if one does not already exist
#   4. install the delegation skill to ~/.agents/skills/delegation/SKILL.md
#      (a copy, not a symlink into this repo -- see docs/USER_INSTALLATION.md
#      for why) and link it for Claude Code discovery if that pattern is
#      present on this machine
#
# No sudo. No provider authentication changes. No model calls. Safe to
# re-run for an update/reinstall -- it never touches an existing config, and
# only ever writes its own skill file.
#
# Usage:
#   scripts/install-user-delegation.sh            # install/update
#   scripts/install-user-delegation.sh --uninstall # remove the runtime
#
# Uninstall removes the pipx install and the skill files it created. It does
# NOT delete your config (~/.config/agent-delegation/) or logs
# (~/.local/state/agent-delegation/) -- remove those yourself if you want a
# full wipe.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGE_NAME="agent-delegation-benchmark"

XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
XDG_STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"
CONFIG_DIR="$XDG_CONFIG_HOME/agent-delegation"
CONFIG_FILE="$CONFIG_DIR/config.toml"
STATE_LOG_DIR="$XDG_STATE_HOME/agent-delegation/delegate_runs"

AGENTS_SKILL_DIR="$HOME/.agents/skills/delegation"
AGENTS_SKILL_FILE="$AGENTS_SKILL_DIR/SKILL.md"
CLAUDE_SKILL_LINK="$HOME/.claude/skills/delegation"

uninstall() {
  echo "Uninstalling ${PACKAGE_NAME} (pipx)..."
  if command -v pipx >/dev/null 2>&1; then
    pipx uninstall "$PACKAGE_NAME" || echo "  (pipx reported nothing to uninstall)"
  else
    echo "  pipx not found; nothing to uninstall via pipx"
  fi
  if [ -L "$CLAUDE_SKILL_LINK" ]; then
    rm "$CLAUDE_SKILL_LINK"
    echo "Removed $CLAUDE_SKILL_LINK"
  fi
  if [ -f "$AGENTS_SKILL_FILE" ]; then
    rm "$AGENTS_SKILL_FILE"
    rmdir "$AGENTS_SKILL_DIR" 2>/dev/null || true
    echo "Removed $AGENTS_SKILL_FILE"
  fi
  echo "Config preserved at: $CONFIG_FILE (delete manually if you want a full wipe)"
  echo "Logs preserved at:   $STATE_LOG_DIR"
  exit 0
}

if [ "${1:-}" = "--uninstall" ]; then
  uninstall
fi

echo "== 1/4: no-model checks =="
cd "$REPO_ROOT"
python -m unittest discover -s tests -q
python -m delegation.preflight

echo
echo "== 2/4: installing user-level commands (pipx) =="
if ! command -v pipx >/dev/null 2>&1; then
  echo "pipx not found on PATH. Install it first (no sudo needed), e.g.:" >&2
  echo "  python3 -m pip install --user pipx && python3 -m pipx ensurepath" >&2
  exit 1
fi
pipx install --force "$REPO_ROOT"

echo
echo "== 3/4: initial config =="
if [ -f "$CONFIG_FILE" ]; then
  echo "Existing config found, left untouched: $CONFIG_FILE"
else
  mkdir -p "$CONFIG_DIR"
  python3 -c "
from delegation.config import default_config, save_config
from pathlib import Path
save_config(default_config(), Path(r'''$CONFIG_FILE'''))
"
  echo "Created default config: $CONFIG_FILE"
fi

echo
echo "== 4/4: installing skill =="
mkdir -p "$AGENTS_SKILL_DIR"
cp "$REPO_ROOT/skills/delegation/SKILL.md" "$AGENTS_SKILL_FILE"
echo "Installed skill: $AGENTS_SKILL_FILE"
if [ -d "$HOME/.claude/skills" ]; then
  if [ -e "$CLAUDE_SKILL_LINK" ] || [ -L "$CLAUDE_SKILL_LINK" ]; then
    if [ -L "$CLAUDE_SKILL_LINK" ] && [ "$(readlink "$CLAUDE_SKILL_LINK")" = "../../.agents/skills/delegation" ]; then
      echo "Claude Code skill link already present: $CLAUDE_SKILL_LINK"
    else
      echo "Skipped: $CLAUDE_SKILL_LINK already exists and is not our link; not overwriting unrelated content"
    fi
  else
    ln -s "../../.agents/skills/delegation" "$CLAUDE_SKILL_LINK"
    echo "Linked for Claude Code: $CLAUDE_SKILL_LINK -> ../../.agents/skills/delegation"
  fi
else
  echo "No ~/.claude/skills directory found; skipping Claude Code link (skill source is still installed)"
fi

echo
echo "== Done =="
echo "Commands:"
for cmd in ask-flash ask-haiku ask-sonnet ask-deepseek-pro ask-deepseek-flash ask-minimax-m3 delegate-status delegate-config; do
  path="$(command -v "$cmd" 2>/dev/null || echo "NOT ON PATH")"
  echo "  $cmd: $path"
done
echo "Config: $CONFIG_FILE"
echo "Logs:   $STATE_LOG_DIR"
echo "Skill:  $AGENTS_SKILL_FILE"
echo
echo "If a command shows 'NOT ON PATH', run: pipx ensurepath (then open a new shell)"
