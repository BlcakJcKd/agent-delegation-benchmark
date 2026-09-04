"""Controller and public-verifier evaluation for V2.4."""
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
MODULE_PREFIXES = ["dispatchboard"]


def _clean_modules() -> None:
    for name in list(sys.modules):
        if any(name == prefix or name.startswith(prefix + ".") for prefix in MODULE_PREFIXES):
            del sys.modules[name]


def _safe(name: str, function) -> dict[str, Any]:
    try:
        return {"name": name, "passed": bool(function()), "detail": ""}
    except Exception as exc:
        # Type names are useful for diagnosis and do not expose host paths or
        # candidate content.
        return {"name": name, "passed": False, "detail": type(exc).__name__}


def _checks(root: Path) -> list[dict[str, Any]]:
    _clean_modules()
    sys.path.insert(0, str(root))
    from dispatchboard.api import WorkspaceAPI
    from dispatchboard.service import WorkspaceService

    def service():
        data = json.loads((root / "data/workspace.json").read_text())
        return WorkspaceService(data["tickets"], data["projects"], data["users"])

    def c1():
        api = WorkspaceAPI(service())
        item = api.create_bookmark("alice", "urgent work", {"status": " open ", "labels": [" urgent "]})
        expected = api.tickets(status="open", labels=["urgent"])
        return item["owner"] == "alice" and item["name"] == "urgent work" and [x.identifier for x in api.run_bookmark("alice", "urgent work")] == [x.identifier for x in expected]

    def c2():
        api = WorkspaceAPI(service())
        api.create_bookmark("alice", "active", {"status": "open"})
        before = [x.identifier for x in api.run_bookmark("alice", "active")]
        target = api.tickets(status="open")[0]
        api.update(target.identifier, {"status": "closed"}, actor="alice")
        after = [x.identifier for x in api.run_bookmark("alice", "active")]
        return target.identifier in before and target.identifier not in after and before != after

    def c3():
        api = WorkspaceAPI(service())
        api.create_bookmark("alice", "mine", {"owner": "alice"})
        api.create_bookmark("bob", "mine", {"owner": "bob"})
        return api.list_bookmarks("alice") == ["mine"] and api.list_bookmarks("bob") == ["mine"] and all(item.owner == "alice" for item in api.run_bookmark("alice", "mine"))

    def c4():
        api = WorkspaceAPI(service())
        api.create_bookmark("alice", "one", {"project": "atlas"})
        api.create_bookmark("alice", "two", {"project": "beacon", "labels": ["urgent"]})
        try:
            api.create_bookmark("alice", "one", {"status": "closed"})
        except Exception:
            collision = True
        else:
            collision = False
        return collision and api.list_bookmarks("alice") == ["one", "two"]

    def c5():
        api = WorkspaceAPI(service())
        api.create_bookmark("alice", "portable", {"project": "cinder", "text": "fractional"})
        payload = api.export_bookmarks("alice")
        other = WorkspaceAPI(service())
        other.import_bookmarks("cara", payload)
        return other.list_bookmarks("cara") == ["portable"] and [x.identifier for x in other.run_bookmark("cara", "portable")] == [x.identifier for x in api.run_bookmark("alice", "portable")]

    def c6():
        api = WorkspaceAPI(service())
        api.create_bookmark("alice", "report", {"project": "atlas"})
        report = api.bookmark_report("alice", "report")
        return report["bookmark"] == "report" and report["owner"] == "alice" and report["query"]["project"] == "atlas" and report["summary"]["count"] == len(api.run_bookmark("alice", "report"))

    def c7():
        api = WorkspaceAPI(service())
        api.create_bookmark("alice", "compound", {"status": "opened", "owner": " ALICE ", "labels": [" URGENT ", "core"], "text": "REPAIR"})
        result = api.run_bookmark("alice", "compound")
        return all(item.status == "open" and item.owner == "alice" and {"urgent", "core"}.issubset(item.labels) and "repair" in item.title.casefold() for item in result)

    def c8():
        api = WorkspaceAPI(service())
        api.create_bookmark("alice", "remove", {"status": "blocked"})
        present = api.list_bookmarks("alice")
        api.delete_bookmark("alice", "remove")
        return present == ["remove"] and api.list_bookmarks("alice") == [] and api.report()["summary"]["count"] == len(api.tickets())

    names = ["bookmark creation", "dynamic bookmark execution", "owner isolation", "bookmark lifecycle", "bookmark portability", "bookmark reporting", "compound query behavior", "delete and old API compatibility"]
    return [_safe(name, function) for name, function in zip(names, [c1, c2, c3, c4, c5, c6, c7, c8])]


def _old_contract(instance: Any, root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="ekalavya-v24-old-contract-") as directory:
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
        checks = _checks(root)
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
