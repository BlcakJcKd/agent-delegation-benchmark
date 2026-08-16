"""XDG-compatible path resolution for the installed, repo-independent runtime.

Nothing here depends on the source repository's location or on ``__file__``;
every path is derived from environment variables and the user's home
directory per the XDG Base Directory Specification, so it resolves the same
way whether this package is imported from a source checkout or from an
installed site-packages copy.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "agent-delegation"


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / APP_NAME


def config_path() -> Path:
    return config_dir() / "config.toml"


def state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".local" / "state"
    return root / APP_NAME


def log_root() -> Path:
    return state_dir() / "delegate_runs"
