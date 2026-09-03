"""Controller-owned V2.3 evaluator for the public feature contract."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

CHECK_COUNT = 8
MODULE_PREFIXES = ["inventory"]


def _clean_modules() -> None:
    for name in list(sys.modules):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in MODULE_PREFIXES):
            del sys.modules[name]


def _safe(name: str, fn) -> dict[str, Any]:
    try:
        return {"name": name, "passed": bool(fn()), "detail": ""}
    except Exception as exc:
        return {"name": name, "passed": False, "detail": type(exc).__name__}


def _new_checks(root: Path) -> list[dict[str, Any]]:
    _clean_modules()
    sys.path.insert(0, str(root))
    from inventory.api import InventoryAPI
    from inventory.service import InventoryService

    records = json.loads((root / "data/products.json").read_text())

    def c1():
        service = InventoryService(records)
        api = InventoryAPI(service)
        token = api.create_snapshot("baseline")
        return token["name"] == "baseline" and [x.identifier for x in api.snapshot_products(token)] == [17, 44, 63, 88, 101]

    def c2():
        service = InventoryService(records)
        token = service.create_snapshot("before")
        service.mutate(101, {**records[0], "amount": 20.25})
        return service.summary()["total"] == 39.5 and service.snapshot_report(token)["summary"]["total"] == 31.5

    def c3():
        service = InventoryService(records)
        first = service.create_snapshot("one")
        service.add({"id": 120, "name": "epsilon", "category": "hardware", "amount": 1.25, "tags": []})
        second = service.create_snapshot("two")
        return len(service.list_products_at(first)) == 5 and len(service.list_products_at(second)) == 6 and {x["name"] for x in service.list_snapshot_names()} == {"one", "two"}

    def c4():
        service = InventoryService(records)
        token = service.create_snapshot("lookup")
        first = service.list_products_at(token)
        second = service.list_products_at(token)
        return [x.identifier for x in service.find(" alpha ", "hardware")] == [63, 101] and [x.identifier for x in first] == [x.identifier for x in second]

    def c5():
        service = InventoryService(records)
        token = service.create_snapshot("scope")
        return [x.identifier for x in service.list_products_at(token, "software")] == [17, 88] and service.snapshot_report(token, "hardware")["summary"]["count"] == 2

    def c6():
        service = InventoryService(records)
        token = service.create_snapshot("wire")
        restored = service.restore_snapshot(service.export_snapshot(token))
        return restored["name"] == "wire" and restored["version"] == 0 and len(service.list_products_at(restored)) == 5

    def c7():
        service = InventoryService(records)
        token = service.create_snapshot("report")
        report = service.snapshot_report(token)
        return report["snapshot"] == "report" and report["version"] == 0 and report["ids"] == [17, 44, 63, 88, 101] and report["summary"]["by_category"]["hardware"] == 16.0

    def c8():
        service = InventoryService(records)
        token = service.create_snapshot("compat")
        before = service.report()
        service.mutate(17, {**records[1], "amount": 7.5})
        return before["ids"] == [17, 44, 63, 88, 101] and service.report()["version"] == 1 and service.list_products_at(token)[0].amount == 4.5

    return [_safe(name, fn) for name, fn in zip(
        ["snapshot creation", "snapshot stability", "independent snapshots", "snapshot cache and lookup", "snapshot category scope", "snapshot serialization", "snapshot reporting", "old API compatibility"],
        [c1, c2, c3, c4, c5, c6, c7, c8],
    )]


def _old_contract(instance: Any, root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ekalavya-v23-old-contract-") as directory:
        tests = Path(directory) / "tests"
        tests.mkdir()
        tests.joinpath("test_old_contract.py").write_text(textwrap.dedent(instance.files["tests/test_old_contract.py"]).lstrip(), encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": str(root)}
        try:
            result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", str(tests), "-q"], cwd=root, env=env, text=True, capture_output=True, timeout=30, check=False)
            return {"passed": result.returncode == 0, "returncode": result.returncode, "detail": result.stderr[-1000:]}
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"passed": False, "returncode": None, "detail": type(exc).__name__}


def evaluate(instance: Any, root: Path) -> dict[str, Any]:
    old = _old_contract(instance, root)
    try:
        checks = _new_checks(root)
    except Exception as exc:
        checks = [{"name": "setup", "passed": False, "detail": type(exc).__name__}] + [{"name": f"unavailable-{i}", "passed": False, "detail": "setup_failed"} for i in range(2, CHECK_COUNT + 1)]
    finally:
        _clean_modules()
    if len(checks) != CHECK_COUNT:
        raise ValueError("malformed evaluator vector")
    vector = [bool(item["passed"]) for item in checks]
    score = 100.0 * sum(vector) / CHECK_COUNT
    return {
        "checks": checks,
        "check_vector": vector,
        "new_feature_score": score,
        "score": score,
        "old_contract_tests_passed_after": old["passed"],
        "old_contract_detail": old,
        "old_contract_regressions": 0 if old["passed"] else 1,
        "full_pass": all(vector) and old["passed"],
    }
