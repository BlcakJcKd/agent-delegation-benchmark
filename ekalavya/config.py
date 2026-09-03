"""Reversible legacy configuration migration and Ekalavya state paths."""

from __future__ import annotations

import os
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .schema import CandidateIdentity


def config_root() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")).expanduser() / "ekalavya"


def legacy_root() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")).expanduser() / "agent-delegation"


def migrate_legacy_config(source: Path | None = None, target: Path | None = None) -> dict[str, object]:
    source = source or legacy_root(); target = target or config_root()
    report: dict[str, object] = {"source": str(source), "target": str(target), "copied": [], "skipped": [], "conflicts": []}
    if not source.is_dir():
        report["decision"] = "legacy config absent; created no replacement"
        return report
    if source.is_symlink() or target.is_symlink():
        report["decision"] = "refused symlinked config root"
        report["conflicts"] = ["symlinked-root"]
        return report
    target.mkdir(parents=True, exist_ok=True, mode=0o700); os.chmod(target, 0o700)
    for item in sorted(source.rglob("*")):
        rel = item.relative_to(source); dest = target / rel
        if item.is_symlink():
            report["skipped"].append(str(rel)); continue
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True, mode=0o700); os.chmod(dest, 0o700); continue
        if dest.exists():
            if dest.read_bytes() == item.read_bytes(): report["skipped"].append(str(rel))
            else: report["conflicts"].append(str(rel))
            continue
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(item, dest)
        os.chmod(dest, item.stat().st_mode & 0o777)
        report["copied"].append(str(rel))
    report["decision"] = "copied without deleting legacy tree; rerunnable and conflict-preserving"
    report["timestamp"] = datetime.now(timezone.utc).isoformat()
    return report


def ensure_control_files(target: Path | None = None) -> dict[str, object]:
    """Create additive Ekalavya catalogue/profile files from fixed route metadata."""
    target = target or config_root(); target.mkdir(parents=True, exist_ok=True, mode=0o700); os.chmod(target, 0o700)
    catalogue_path, profiles_path = target / "catalogue.json", target / "profiles.json"
    if catalogue_path.exists() or profiles_path.exists():
        return {"created": [], "skipped": [name for name, path in (("catalogue.json", catalogue_path), ("profiles.json", profiles_path)) if path.exists()]}
    from delegation import routing
    from delegation.core import DELEGATES
    catalogue=[]; profiles=[]
    for route, spec in sorted(DELEGATES.items()):
        identity = CandidateIdentity(routing.ROUTE_PROVIDER[route], route, spec.model, route, capabilities={"reasoning_values": [spec.effort] if spec.effort else []})
        item = identity.as_dict(); item.update({"identity_key": identity.identity_key, "lifecycle": "current", "legacy_route": route, "transport": routing.ROUTE_TRANSPORT.get(route)})
        catalogue.append(item)
        profiles.append({"name": route, "description": f"Migrated explicit legacy route {route}", "default_identity_key": identity.identity_key, "permitted_candidates": [identity.identity_key], "reasoning_policy": "fixed", "default_reasoning": spec.effort})
    for path, value in ((catalogue_path, catalogue), (profiles_path, profiles)):
        path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n"); os.chmod(path, 0o600)
    return {"created": ["catalogue.json", "profiles.json"], "skipped": []}
