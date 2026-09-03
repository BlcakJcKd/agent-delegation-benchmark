"""Objective, visible-contract scoring for public characterization fixtures.

There is intentionally no hidden evaluator or controller-side repair in a
generated instance.  These checks independently exercise the documented
acceptance contract after the candidate has finished editing its workspace.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

from .generate import TaskInstance


def _check(name: str, passed: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _visible_tests(workspace: Path) -> dict[str, Any]:
    env = {**os.environ, "PYTHONPATH": str(workspace)}
    try:
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"],
            cwd=workspace, env=env, text=True, capture_output=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"passed": False, "returncode": None, "stdout": "", "stderr": str(exc)}
    return {"passed": result.returncode == 0, "returncode": result.returncode, "stdout": result.stdout[-4000:], "stderr": result.stderr[-4000:]}


def _p1(workspace: Path, instance: TaskInstance) -> list[dict[str, Any]]:
    from app.catalog import find, sorted_ids, summarize
    from app.store import DerivedTotals, Store
    items = json.loads((workspace / "data/items.json").read_text())
    store = Store({"numbers": f"{instance.variant['first']}, {instance.variant['second']}"})
    totals = DerivedTotals(store)
    first = instance.variant["first"] + instance.variant["second"]
    checks = [
        _check("derived total", totals.total("numbers") == first),
        _check("derived cache", totals.total("numbers") == first and totals.parse_calls == 1),
    ]
    store.put("numbers", f"{instance.variant['first'] + 1}, {instance.variant['second']}")
    checks.extend([
        _check("version invalidation", totals.total("numbers") == first + 1),
        _check("versioned parse count", totals.parse_calls == 2),
        _check("normalized lookup", len(find(items, " alpha ")) == 2),
        _check("ascending identifiers", sorted_ids(items) == [10, 20, 30]),
        _check("summary count", summarize(items)["count"] == 3),
        _check("summary total", summarize(items)["total"] == instance.variant["first"] + instance.variant["second"] + 4),
    ])
    return checks


def _p2(workspace: Path, instance: TaskInstance) -> list[dict[str, Any]]:
    from settings.loader import load_settings
    from settings.state import Session
    import tempfile
    fd, config_name = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    config = Path(config_name)
    config.write_text(json.dumps({"mode": "file", "limit": 4, "enabled": False}))
    try:
        checks = [
            _check("default precedence", load_settings()["mode"] == "safe"),
            _check("file precedence", load_settings(config)["limit"] == 4),
            _check("environment precedence", load_settings(config, {"APP_LIMIT": "7"})["limit"] == 7),
            _check("CLI precedence", load_settings(config, {"APP_LIMIT": "7"}, ["--limit=9"])["limit"] == 9),
            _check("typed booleans", load_settings(environ={"APP_ENABLED": "true"})["enabled"] is True),
        ]
    finally:
        config.unlink(missing_ok=True)
    session = Session()
    first = session.load("ada")
    second = session.load("lin")
    session.reset()
    checks.extend([
        _check("user isolation", first["user"] == "ada" and second["user"] == "lin"),
        _check("active state", session.current is None),
        _check("state values", first["limit"] == 10 and second["limit"] == 10),
    ])
    return checks


def _p3(workspace: Path, instance: TaskInstance) -> list[dict[str, Any]]:
    from pipeline.core import load_rows, split_by_group, summarize
    from pipeline.metrics import ordered
    rows = load_rows(str(workspace / "data/measurements.csv"))
    # The fixture deliberately contains a global-randomness defect.  The
    # evaluator itself must remain deterministic while measuring that defect.
    random_state = random.getstate()
    try:
        random.seed(instance.seed)
        train1, eval1 = split_by_group(rows, 0.5)
        random.seed(instance.seed)
        train2, eval2 = split_by_group(rows, 0.5)
    finally:
        random.setstate(random_state)
    train_groups, eval_groups = {r["group"] for r in train1}, {r["group"] for r in eval1}
    ordered_rows = ordered(rows)
    expected = [("A", "2024-01-01"), ("A", "2024-01-02"), ("B", "2024-01-01"), ("B", "2024-01-02")]
    checks = [
        _check("all rows retained", len(rows) == 4 and len(train1) + len(eval1) == 4),
        _check("chronological ordering", [(r["group"], r["timestamp"]) for r in ordered_rows] == expected),
        _check("group disjoint split", train_groups.isdisjoint(eval_groups) and train_groups | eval_groups == {"A", "B"}),
        _check("deterministic split", train1 == train2 and eval1 == eval2),
        _check("no global shuffle", rows[0]["group"] == "A" and rows[1]["group"] == "B"),
        _check("summary count", summarize(rows)["count"] == 4),
        _check("summary mean", summarize(rows)["mean"] == 7.5),
        _check("numeric preservation", sum(float(r["value"]) for r in rows) == 30.0),
    ]
    return checks


def _p4(workspace: Path, instance: TaskInstance) -> list[dict[str, Any]]:
    from compatpkg import Client, Service, decode, encode, make_client
    from compatpkg.legacy import old_client
    from compatpkg.new_api import service
    client = make_client("visible")
    checks = [
        _check("service type", isinstance(service("s"), Service)),
        _check("client compatibility", isinstance(client, Client) and isinstance(old_client("old"), Client)),
        _check("default timeout", client.request("/x")["timeout"] == 30),
        _check("per request timeout", client.request("/x", timeout=instance.variant["threshold"])["timeout"] == instance.variant["threshold"]),
        _check("factory timeout", make_client("x", 12).timeout == 12),
        _check("codec round trip", decode(encode(client))["name"] == "visible"),
        _check("codec default", decode('{"name":"legacy"}')["timeout"] == 30),
        _check("new service request", service("new", 8).request("/new")["timeout"] == 8),
    ]
    return checks


def evaluate(instance: TaskInstance, workspace: Path) -> dict[str, Any]:
    visible = _visible_tests(workspace)
    workspace_text = str(workspace)
    sys.path.insert(0, workspace_text)
    try:
        checks = {"P1_multi_file_debug": _p1, "P2_config_state": _p2, "P3_data_pipeline": _p3, "P4_compat_refactor": _p4}[instance.family](workspace, instance)
    finally:
        if sys.path and sys.path[0] == workspace_text:
            sys.path.pop(0)
    passed = sum(check["passed"] for check in checks)
    total = len(checks)
    return {
        "evaluation_class": "public_characterization",
        "objective": True,
        "adversarial_isolation": False,
        "authoritative_reference_present": False,
        "checks": checks,
        "score": (100.0 * passed / total) if total else None,
        "maximum": 100.0,
        "full_pass": passed == total,
        "public_tests": visible,
        "scope_compliance": True,
        "visible_evaluator_only": True,
    }
