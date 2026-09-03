"""Canonical Ekalavya CLI with read-only status/history/spend foundations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from delegation import routing
from delegation.config import load_config, save_config, set_enabled
from delegation.status_cli import build_report
from delegation.vllm import inspect_vllm_routes

from . import __version__
from .catalogue import load_catalogue, save_catalogue
from .config import config_root, migrate_legacy_config
from .executor import execute
from .ledger import connect, default_db_path, finalize_run, record_availability, record_resolution, record_run, upsert_model
from .migrate import migrate_all
from .resolver import resolve
from .schema import CandidateIdentity, RunIntent


def _paths() -> tuple[Path, Path, Path]:
    root = config_root(); return root, root / "catalogue.json", root / "profiles.json"


def _profiles(path: Path) -> list[dict[str, Any]]:
    if not path.is_file(): return []
    value = json.loads(path.read_text()); return value if isinstance(value, list) else []


def _named_route_profile(name: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
    """Expose a configured named vLLM route through the generic run contract."""
    if not name.startswith("vllm:") or not name[5:]:
        return None
    route = name[5:]
    info = inspect_vllm_routes().get(route)
    config = load_config()
    if info is None or info.provider is None or not config.get("vllm", {}).get(route, {"enabled": True}).get("enabled", True):
        return None
    provider = info.provider
    identity = CandidateIdentity(
        "vllm", "openai-compatible", provider.model, route,
        capabilities={"harness_values": ["vllm"]},
    )
    entry = identity.as_dict()
    entry.update({
        "identity_key": identity.identity_key,
        "lifecycle": "current",
        "execution_route": f"vllm:{route}",
        "transport": "openai-compatible",
        "harness": "vllm",
        "harness_version": None,
    })
    profile = {
        "name": name,
        "description": f"Configured named vLLM route {route}",
        "default_identity_key": identity.identity_key,
        "permitted_candidates": [identity.identity_key],
        "reasoning_policy": "overrideable",
    }
    return profile, entry


def _json_or_text(value: Any, as_json: bool) -> None:
    if as_json: print(json.dumps(value, indent=2, sort_keys=True))
    else: print(value if isinstance(value, str) else json.dumps(value, indent=2, sort_keys=True))


def _vllm_summary() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for name, info in inspect_vllm_routes().items():
        provider = info.provider
        result[name] = {
            "state": "available" if provider else info.error_kind or "invalid-configuration",
            "model": provider.model if provider else None,
            "shared_compute": provider.shared_compute if provider else None,
            "max_concurrency": provider.max_concurrency if provider else None,
            "thinking_default": provider.thinking_default if provider else None,
            "default_max_tokens": provider.default_max_tokens if provider else None,
            "max_tokens_cap": provider.max_tokens_cap if provider else None,
            "credential_configured": bool(provider) if provider else None,
        }
    return result


def _availability_payload(config: dict[str, Any]) -> dict[str, Any]:
    return {"availability": config, "vllm_routes": _vllm_summary()}


def cmd_status(args: argparse.Namespace) -> int:
    root, cat, prof = _paths(); entries = load_catalogue(cat); profiles = _profiles(prof)
    try:
        routing_report = build_report(getattr(args, "primary", None), live=getattr(args, "live", False))
    except ValueError as exc:
        print(f"status error: {exc}", file=sys.stderr); return 2
    result = {"product": "Ekalavya", "version": __version__, "primary": getattr(args, "primary", None), "config_root": str(root), "ledger": str(default_db_path()), "profiles": [{"name": p.get("name"), "default": p.get("default_identity_key"), "reasoning_policy": p.get("reasoning_policy", "overrideable"), "availability": "configured" if p.get("default_identity_key") else "not-configured"} for p in profiles], "catalogue": [{k: e.get(k) for k in ("provider", "family", "provider_model_id", "lifecycle", "identity_key")} for e in entries], "routing": routing_report}
    _json_or_text(result, args.json); return 0


def cmd_profiles(args: argparse.Namespace) -> int:
    _, _, path = _paths(); _json_or_text(_profiles(path), args.json); return 0


def cmd_models(args: argparse.Namespace) -> int:
    _, path, _ = _paths()
    if getattr(args, "refresh", False):
        # Explicit refresh is intentionally file-driven in V1; it cannot silently
        # contact providers or promote candidates.
        if not args.source:
            print("models refresh requires --source FILE (provider discovery output); no network discovery performed", file=sys.stderr); return 2
        incoming = json.loads(Path(args.source).read_text())
        if not isinstance(incoming, list):
            print("models refresh source must contain a JSON list", file=sys.stderr); return 2
        current = load_catalogue(path); known = {e.get("identity_key") for e in current}; added = 0
        conn = connect(); observed_at = datetime.now(timezone.utc).isoformat()
        for raw in incoming:
            item = dict(raw)
            if not item.get("identity_key"):
                item["identity_key"] = CandidateIdentity(**{k: item.get(k) for k in CandidateIdentity.__dataclass_fields__}).identity_key
            existing = next((e for e in current if e.get("identity_key") == item["identity_key"]), None)
            item["lifecycle"] = existing.get("lifecycle", "candidate") if existing else "candidate"
            if item.get("identity_key") not in known:
                current.append(item); known.add(item.get("identity_key")); added += 1
            identity = CandidateIdentity(**{k: item.get(k) for k in CandidateIdentity.__dataclass_fields__})
            model_id = upsert_model(conn, identity, lifecycle=item["lifecycle"], discovered_at=observed_at)
            record_availability(conn, model_id, state="available", observed_at=observed_at, source=item.get("discovery_source", "provider discovery"), details={k: v for k, v in item.items() if k not in CandidateIdentity.__dataclass_fields__})
        save_catalogue(path, current); _json_or_text({"added_candidates": added, "auto_promoted": 0}, args.json); return 0
    entries = load_catalogue(path)
    routes = _vllm_summary()
    _json_or_text({"catalogue": entries, "named_routes": routes} if routes else entries, args.json); return 0


def cmd_config(args: argparse.Namespace) -> int:
    if getattr(args, "action", None) == "migrate":
        result = migrate_all(); _json_or_text(result, args.json); return 0
    config = load_config(); action = getattr(args, "action", None)
    if action in (None, "list"):
        root, _, _ = _paths(); _json_or_text({"config_root": str(root), "migration": "explicit via eka config migrate", **_availability_payload(config)}, args.json); return 0
    target = getattr(args, "target", None)
    if not target:
        print(f"config {action} requires a target", file=sys.stderr); return 2
    if action in {"enable", "disable"}:
        if target in config.get("models", {}): section = "models"
        elif target in config.get("vllm", {}): section = "vllm"
        else:
            print(f"unknown configured route: {target}", file=sys.stderr); return 2
        updated = set_enabled(config, section, target, action == "enable", reason=getattr(args, "reason", None))
    elif action in {"enable-provider", "disable-provider"}:
        if target not in config.get("providers", {}):
            print(f"unknown provider: {target}", file=sys.stderr); return 2
        updated = set_enabled(config, "providers", target, action == "enable-provider", reason=getattr(args, "reason", None))
        section = "providers"
    else:
        print(f"unknown config action: {action}", file=sys.stderr); return 2
    save_config(updated)
    _json_or_text({"action": action, "target": target, **_availability_payload(updated)}, args.json)
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    conn = connect(); clauses=[]; values=[]
    if args.profile: clauses.append("profile=?"); values.append(args.profile)
    if args.provider: clauses.append("provider=?"); values.append(args.provider)
    if args.model: clauses.append("identity_key=?"); values.append(args.model)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = [dict(r) for r in conn.execute("SELECT run_id,started_at,ended_at,profile,provider,identity_key,status FROM runs" + where + " ORDER BY started_at DESC LIMIT ?", (*values, args.limit))]
    _json_or_text(rows, args.json); return 0


def cmd_spend(args: argparse.Namespace) -> int:
    conn = connect(); rows = [dict(r) for r in conn.execute("SELECT billing_mode, cost_source, currency, SUM(provider_reported_cost) AS provider_reported, SUM(calculated_cost) AS calculated, SUM(api_equivalent_cost) AS api_equivalent, COUNT(*) AS observations FROM cost_observations GROUP BY billing_mode,cost_source,currency")]
    _json_or_text({"semantics": {"actual": "provider_reported_cost", "calculated": "calculated_cost", "api_equivalent": "api_equivalent_cost", "unknown": "null; never inferred"}, "groups": rows}, args.json); return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    root, cat, prof = _paths(); integrity = True
    if default_db_path().exists():
        try: integrity = connect().execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        except sqlite3.DatabaseError: integrity = False
    checks = {"config_dir_private": root.exists() and (root.stat().st_mode & 0o777) == 0o700 if root.exists() else True, "catalogue_readable": not cat.exists() or cat.is_file(), "profiles_readable": not prof.exists() or prof.is_file(), "availability_config_readable": not (root / "config.toml").exists() or (root / "config.toml").is_file(), "ledger_parent": default_db_path().parent.exists(), "ledger_integrity": integrity}
    _json_or_text(checks, args.json); return 0 if all(checks.values()) else 1


def cmd_run(args: argparse.Namespace) -> int:
    root, cat, prof = _paths(); profiles = {p.get("name"): p for p in _profiles(prof)}
    catalogue = load_catalogue(cat)
    dynamic = _named_route_profile(args.profile)
    if dynamic:
        profiles[args.profile], named_entry = dynamic
        catalogue = catalogue + [named_entry]
    if args.profile not in profiles:
        print(f"profile unavailable: {args.profile}; no automatic provider failover", file=sys.stderr); return 2
    intent = RunIntent(args.profile, args.provider, args.family, args.model, args.reasoning, args.harness, str(args.workspace) if args.workspace else None, str(args.prompt_file) if args.prompt_file else None, args.primary, args.timeout)
    resolution = resolve(intent, profiles[args.profile], catalogue); record = resolution.as_dict(); run_id = uuid.uuid4().hex
    conn = connect(); record_run(conn, run_id, intent.__dict__, resolved=record.get("resolved"), status=resolution.state, resolution_reason=resolution.reason, provider=(resolution.candidate.provider if resolution.candidate else None), identity_key=(resolution.candidate.identity_key if resolution.candidate else None)); record_resolution(conn, run_id, intent.__dict__, record)
    if args.prompt_file and resolution.state != "resolved": _json_or_text({"run_id": run_id, **record}, args.json); return 3
    if args.prompt_file:
        if not args.workspace:
            _json_or_text({"run_id": run_id, **record, "execution": {"state": "workspace-required", "reason": "a writable/read-only workspace must be explicit"}}, args.json); return 3
        execution = execute(record, args.prompt_file, args.workspace, primary=args.primary, timeout_seconds=args.timeout)
        evidence = execution.get("evidence")
        if evidence:
            evidence_path = Path(str(evidence))
            metadata_path = evidence_path / "execution.json"
            digest = hashlib.sha256(metadata_path.read_bytes()).hexdigest() if metadata_path.is_file() else None
            finalize_run(conn, run_id, status="completed" if execution.get("state") == "completed" else "failed", raw_evidence_path=str(evidence_path), raw_evidence_sha256=digest)
        _json_or_text({"run_id": run_id, **record, "execution": execution}, args.json); return 0 if execution.get("state") == "completed" else 4
    _json_or_text({"run_id": run_id, **record}, args.json); return 0 if resolution.state == "resolved" else 3


def cmd_bench(args: argparse.Namespace) -> int:
    print("Ekalavya benchmark subsystem delegates to the existing benchmark.runner; no benchmark mutation is performed by this command.")
    return 0


def _parser() -> argparse.ArgumentParser:
    p=argparse.ArgumentParser(prog="ekalavya", description="Ekalavya delegation control plane")
    p.add_argument("--version", action="version", version=__version__); sub=p.add_subparsers(dest="command", required=True)
    def common(q): q.add_argument("--json", action="store_true")
    q=sub.add_parser("status", help="network-free catalogue/profile overview"); q.add_argument("--primary"); q.add_argument("--live", action="store_true", help="perform explicit GET-only shared-route observability checks"); common(q); q.set_defaults(func=cmd_status)
    q=sub.add_parser("profiles", help="list stable capability profiles, not raw model IDs"); common(q); q.set_defaults(func=cmd_profiles)
    q=sub.add_parser("models", help="list catalogue identities; never promotes or downloads"); q.add_argument("refresh", nargs="?", choices=["refresh"], default=None); q.add_argument("--source", type=Path); common(q); q.set_defaults(func=cmd_models)
    q=sub.add_parser("config", help="inspect or explicitly mutate user-owned availability configuration"); q.add_argument("action", nargs="?", choices=["list", "migrate", "enable", "disable", "enable-provider", "disable-provider"]); q.add_argument("target", nargs="?"); q.add_argument("--reason"); common(q); q.set_defaults(func=cmd_config)
    q=sub.add_parser("history"); q.add_argument("--profile"); q.add_argument("--provider"); q.add_argument("--model"); q.add_argument("--limit", type=int, default=20); common(q); q.set_defaults(func=cmd_history)
    q=sub.add_parser("spend"); common(q); q.set_defaults(func=cmd_spend)
    q=sub.add_parser("doctor"); common(q); q.set_defaults(func=cmd_doctor)
    q=sub.add_parser("bench"); q.set_defaults(func=cmd_bench)
    q=sub.add_parser("run"); q.add_argument("profile"); q.add_argument("--provider"); q.add_argument("--family"); q.add_argument("--model"); q.add_argument("--reasoning"); q.add_argument("--harness"); q.add_argument("--workspace", type=Path); q.add_argument("--prompt-file", type=Path); q.add_argument("--primary"); q.add_argument("--timeout", type=int, default=None); q.add_argument("--json", action="store_true"); q.set_defaults(func=cmd_run)
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "models": args.refresh = args.refresh == "refresh"
    return args.func(args)
