"""Small live model catalogue with explicit lifecycle transitions."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .schema import CandidateIdentity

LIVE_STATES = {"candidate", "current", "previous"}
ALL_STATES = LIVE_STATES | {"retired", "rejected", "removed"}


def _private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)


def load_catalogue(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        raise ValueError("catalogue must be a JSON list")
    return data


def save_catalogue(path: Path, entries: list[dict[str, Any]]) -> None:
    _private_dir(path.parent)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def add_candidate(entries: list[dict[str, Any]], identity: CandidateIdentity, *, state: str = "candidate") -> list[dict[str, Any]]:
    if state not in LIVE_STATES:
        raise ValueError(f"invalid live catalogue state: {state}")
    key = identity.identity_key
    if any(e.get("identity_key") == key for e in entries):
        return entries
    result = list(entries)
    item = identity.as_dict()
    item.update({"identity_key": key, "lifecycle": state, "discovered_at": None})
    result.append(item)
    return result


def transition(entries: list[dict[str, Any]], identity_key: str, target: str) -> list[dict[str, Any]]:
    if target not in ALL_STATES:
        raise ValueError(f"invalid catalogue lifecycle: {target}")
    result = [dict(e) for e in entries]
    match = next((e for e in result if e.get("identity_key") == identity_key), None)
    if match is None:
        raise KeyError(identity_key)
    if target == "current":
        family = (match.get("provider"), match.get("family"))
        for entry in result:
            if (entry.get("provider"), entry.get("family")) == family and entry.get("lifecycle") == "current":
                entry["lifecycle"] = "previous"
    match["lifecycle"] = target
    return result


def selectable(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in entries if e.get("lifecycle") in {"current", "previous", "candidate"}]


def promote(entries: list[dict[str, Any]], identity_key: str, reason: str = "explicit promotion") -> list[dict[str, Any]]:
    return transition(entries, identity_key, "current")


def reject(entries: list[dict[str, Any]], identity_key: str, reason: str = "explicit rejection") -> list[dict[str, Any]]:
    return transition(entries, identity_key, "rejected")


def retire(entries: list[dict[str, Any]], identity_key: str, reason: str = "removed or superseded") -> list[dict[str, Any]]:
    return transition(entries, identity_key, "retired")
