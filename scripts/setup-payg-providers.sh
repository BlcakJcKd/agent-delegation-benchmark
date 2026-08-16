#!/usr/bin/env bash
# Install the non-secret parts of the DeepSeek/MiniMax PAYG Codex provider
# setup: model catalogs, Codex provider profiles, and the four launcher
# scripts (codex-deepseek, codex-minimax, claude-deepseek, claude-minimax).
#
# This script NEVER touches an API key. It installs static, non-secret
# templates from provider_templates/ in this repository, and tells you the
# exact interactive command to run yourself to store each key in the login
# keyring -- it never scripts key entry, so a key can never land in shell
# history or a captured log.
#
# What this does NOT do:
#   - install/authenticate normal OpenAI Codex or normal Anthropic Claude;
#   - install Codex CLI, Claude Code, or pipx (see docs/NEW_MACHINE_SETUP.md);
#   - install the agent-delegation-benchmark runtime itself
#     (scripts/install-user-delegation.sh does that, separately);
#   - use sudo, or silently overwrite a conflicting existing provider config.
#
# Usage:
#   scripts/setup-payg-providers.sh
#
# Safe to re-run: it is a no-op if everything it would write already matches
# exactly, and it refuses (rather than overwrites) if an existing file at
# one of its target paths differs from what it would write.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATES="$REPO_ROOT/provider_templates"

CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
CATALOG_DIR="$CODEX_HOME/model-catalogs"
BIN_DIR="$HOME/.local/bin"

echo "== 1/5: prerequisites =="
missing=0
for cmd in codex claude secret-tool; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "  MISSING: $cmd" >&2
    missing=1
  else
    echo "  OK: $cmd ($(command -v "$cmd"))"
  fi
done
if [ "$missing" -ne 0 ]; then
  cat >&2 <<'EOF'

Prerequisites missing. This script does not install them (no sudo):
  - codex, claude: install per their own current official instructions
    (see docs/NEW_MACHINE_SETUP.md steps 1-5).
  - secret-tool: on Debian/Ubuntu, install the package that provides it
    yourself, e.g.:
        sudo apt install libsecret-tools gnome-keyring
    then ensure a login keyring is unlocked (normal on a graphical login;
    on a headless/SSH session you may need `dbus-run-session` or an
    equivalent, per your distro's keyring documentation).

Re-run this script once all three are available.
EOF
  exit 1
fi

echo
echo "== 2/5: model catalogs =="
mkdir -p "$CATALOG_DIR"
for name in deepseek-v4.json minimax-m3.json; do
  target="$CATALOG_DIR/$name"
  source="$TEMPLATES/codex/model-catalogs/$name"
  if [ -f "$target" ] && ! cmp -s "$source" "$target"; then
    echo "CONFLICT: $target already exists and differs from the template." >&2
    echo "  Not overwriting. Move it aside yourself if you want this script to install the template version, then re-run." >&2
    exit 1
  fi
  cp "$source" "$target"
  echo "  installed: $target"
done

echo
echo "== 3/5: Codex provider profiles =="
for pair in "deepseek.config.toml:deepseek-v4.json" "minimax.config.toml:minimax-m3.json"; do
  profile_name="${pair%%:*}"
  target="$CODEX_HOME/$profile_name"
  rendered="$(sed "s#__CODEX_HOME__#$CODEX_HOME#g" "$TEMPLATES/codex/$profile_name.template")"
  if [ -f "$target" ]; then
    existing="$(cat "$target")"
    if [ "$existing" != "$rendered" ]; then
      echo "CONFLICT: $target already exists and differs from the rendered template." >&2
      echo "  Not overwriting. Move it aside yourself if you want this script to install the template version, then re-run." >&2
      exit 1
    fi
    echo "  already correct: $target"
  else
    printf '%s\n' "$rendered" > "$target"
    echo "  installed: $target"
  fi
done

echo
echo "== 4/5: launcher scripts =="
mkdir -p "$BIN_DIR"
for name in codex-deepseek codex-minimax claude-deepseek claude-minimax; do
  target="$BIN_DIR/$name"
  source="$TEMPLATES/launchers/$name"
  if [ -f "$target" ] && ! cmp -s "$source" "$target"; then
    echo "CONFLICT: $target already exists and differs from the template." >&2
    echo "  Not overwriting. Move it aside yourself if you want this script to install the template version, then re-run." >&2
    exit 1
  fi
  cp "$source" "$target"
  chmod 700 "$target"
  echo "  installed: $target"
done
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  echo "  NOTE: $BIN_DIR is not on PATH in this shell; add it to your shell profile."
fi

echo
echo "== 5/5: keyring credentials (never scripted) =="
for provider in deepseek minimax; do
  if secret-tool lookup service ai-coding-provider provider "$provider" >/dev/null 2>&1; then
    echo "  $provider: an entry already exists in the login keyring (value not checked/printed)."
  else
    echo "  $provider: NO entry found. Store it yourself, interactively (this reads from your terminal, never your shell history):"
    echo "      secret-tool store --label=\"$provider API key\" service ai-coding-provider provider $provider"
  fi
done

cat <<EOF

== Done ==
Installed (non-secret):
  $CODEX_HOME/deepseek.config.toml
  $CODEX_HOME/minimax.config.toml
  $CATALOG_DIR/deepseek-v4.json
  $CATALOG_DIR/minimax-m3.json
  $BIN_DIR/codex-deepseek
  $BIN_DIR/codex-minimax
  $BIN_DIR/claude-deepseek
  $BIN_DIR/claude-minimax

Not installed here (machine-local, out of scope for this script):
  - the API keys themselves (store via 'secret-tool store' above if missing)
  - normal Codex/Claude authentication
  - the agent-delegation-benchmark runtime (run
    scripts/install-user-delegation.sh from this repo for that)

Next: validate with zero model calls --
  python -m delegation.preflight
  delegate-status --primary claude-code
  bwrap --unshare-net --dev /dev --ro-bind / / /bin/true   # sandbox capability check
EOF
