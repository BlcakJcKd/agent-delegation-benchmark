"""Controller-owned pristine evaluator for V2.

This module is never copied into candidate workspaces.  Its checks intentionally
duplicate the public behavioral contract without importing the public verifier.
"""

from __future__ import annotations

import json
import random
import sys
import tempfile
from pathlib import Path
from typing import Any


def _check(name: str, passed: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _clear_modules(prefixes: tuple[str, ...]) -> None:
    for name in list(sys.modules):
        if name.split(".", 1)[0] in prefixes:
            del sys.modules[name]


def _p1(root: Path, instance: Any) -> list[dict[str, Any]]:
    _clear_modules(("app",))
    from app.catalog import find, sorted_ids, summarize
    from app.service import report
    from app.store import DerivedTotals, Store
    items = json.loads((root / "data/items.json").read_text())
    expected = float(items[0]["amount"]) + float(items[1]["amount"])
    store = Store({"numbers": f"{items[0]['amount']},{items[1]['amount']}"})
    totals = DerivedTotals(store)
    first, cached = totals.total("numbers"), totals.total("numbers")
    store.put("numbers", f"{float(items[0]['amount']) + 1},{items[1]['amount']}")
    summary_total = sum(float(item["amount"]) for item in items)
    return [
        _check("initial total", first == expected),
        _check("cache reuse", cached == expected and totals.parse_calls == 1),
        _check("version invalidation", totals.total("numbers") == expected + 1),
        _check("versioned parse count", totals.parse_calls == 2),
        _check("normalized lookup", len(find(items, " alpha ")) == 2),
        _check("ascending identifiers", sorted_ids(items) == [10, 20, 30]),
        _check("fractional summary", summarize(items)["total"] == summary_total),
        _check("cross-module report", report(root / "data/items.json", "alpha")["summary"]["total"] == summary_total),
    ]


def _p2(root: Path, instance: Any) -> list[dict[str, Any]]:
    _clear_modules(("settings",))
    from settings.loader import load_settings
    from settings.state import Session
    config = Path(tempfile.mkstemp(suffix=".json")[1])
    config.write_text(json.dumps({"mode": "file", "limit": 4, "enabled": False}))
    try:
        defaults = load_settings()
        precedence = load_settings(config, {"APP_LIMIT": "7", "APP_ENABLED": "true"}, ["--limit=9"])
    finally:
        config.unlink(missing_ok=True)
    session = Session()
    first, second = session.load("ada"), session.load("lin")
    active_before = session.current.get("user") if session.current else None
    session.invalidate("ada")
    try:
        stale_cleared = session.load("ada") is not first
    except Exception:
        stale_cleared = False
    payload = session.serialize()
    restored = Session(); restored.restore(payload)
    try:
        round_trip = restored.load("lin") == second
    except Exception:
        round_trip = False
    session.reset()
    return [
        _check("default", defaults["mode"] == "safe"),
        _check("precedence", precedence.get("mode") == "file" and precedence.get("limit") == 9),
        _check("typed values", precedence.get("limit") == 9 and precedence.get("enabled") is True),
        _check("user isolation", first["user"] == "ada" and second["user"] == "lin"),
        _check("stale invalidation", stale_cleared),
        _check("active session", active_before == "lin"),
        _check("serialization round trip", round_trip),
        _check("reset", session.current is None),
    ]


def _p3(root: Path, instance: Any) -> list[dict[str, Any]]:
    _clear_modules(("pipeline",))
    from pipeline.core import load_rows, split_by_group, summarize
    from pipeline.metrics import ordered, report
    rows = load_rows(str(root / "data/measurements.csv"))
    random_state = random.getstate()
    try:
        random.seed(instance.seed)
        train1, eval1 = split_by_group(rows)
        train2, eval2 = split_by_group(rows)
    finally:
        random.setstate(random_state)
    expected = [("A", "2024-01-01"), ("A", "2024-01-02"), ("A", "2024-01-03"), ("B", "2024-01-01"), ("B", "2024-01-02"), ("B", "2024-01-03")]
    groups = {row["group"] for row in train1}, {row["group"] for row in eval1}
    original_indexes = {id(row): index for index, row in enumerate(rows)}
    preserves_partition_order = all([original_indexes[id(row)] for row in part] == sorted(original_indexes[id(row)] for row in part) for part in (train1, eval1))
    return [
        _check("all rows retained", len(rows) == 6 and len(train1) + len(eval1) == 6),
        _check("chronological ordering", [(row["group"], row["timestamp"]) for row in ordered(rows)] == expected),
        _check("group-disjoint split", groups[0].isdisjoint(groups[1]) and groups[0] | groups[1] == {"A", "B"}),
        _check("deterministic split", train1 == train2 and eval1 == eval2),
        _check("no global shuffle", preserves_partition_order),
        _check("numeric preservation", sum(float(row["value"]) for row in rows) == 42.0),
        _check("summary", summarize(rows)["count"] == 6 and summarize(rows)["mean"] == 7.0),
        _check("report schema", report(rows)["rows"] == rows),
    ]


def _p4(root: Path, instance: Any) -> list[dict[str, Any]]:
    _clear_modules(("compatpkg",))
    from compatpkg import Client, Service, decode, encode, make_client
    from compatpkg.legacy import old_client
    from compatpkg.new_api import service
    client = make_client("visible")
    try:
        per_request = client.request("/x", timeout=7)["timeout"] == 7
        default_timeout = client.request("/x")["timeout"] == 30
    except (AttributeError, TypeError, KeyError):
        per_request = default_timeout = False
    try:
        factory_timeout = make_client("x", 12).timeout == 12
    except AttributeError:
        factory_timeout = False
    return [
        _check("service type", isinstance(service("s"), Service)),
        _check("legacy compatibility", isinstance(client, Client) and isinstance(old_client("old"), Client) and isinstance(client, Service)),
        _check("per-request timeout", per_request),
        _check("default timeout", default_timeout),
        _check("factory propagation", factory_timeout),
        _check("codec round trip", decode(encode(client)) == {"name": "visible", "timeout": 30}),
        _check("codec default", decode('{"name":"legacy"}')["timeout"] == 30),
        _check("new API request", service("new", 8).request("/new")["timeout"] == 8),
    ]


def evaluate(instance: Any, workspace: Path) -> dict[str, Any]:
    package = {"P1_multi_file_debug": "app", "P2_config_state": "settings", "P3_data_pipeline": "pipeline", "P4_compat_refactor": "compatpkg"}[instance.family]
    workspace_text = str(workspace)
    sys.path.insert(0, workspace_text)
    try:
        checks = {"P1_multi_file_debug": _p1, "P2_config_state": _p2, "P3_data_pipeline": _p3, "P4_compat_refactor": _p4}[instance.family](workspace, instance)
    except Exception as exc:
        checks = [_check(f"controller exception ({package})", False, repr(exc))]
    finally:
        if sys.path and sys.path[0] == workspace_text:
            sys.path.pop(0)
        _clear_modules((package,))
    vector = [bool(check["passed"]) for check in checks]
    passed = sum(vector)
    return {
        "evaluation_class": "public_characterization", "objective": True,
        "checks": checks, "check_vector": vector, "score": 100.0 * passed / len(vector) if vector else None,
        "maximum": 100.0, "full_pass": bool(vector) and passed == len(vector),
    }
