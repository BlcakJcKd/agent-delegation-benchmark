"""Controller-side evaluation for the public R1 behavioral contracts."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from .generate import TaskInstance

CHECK_METHODS = {
    "R1_maintenance": tuple(f"test_c{i}_{name}" for i, name in (
        (1, "fractional_amounts"), (2, "version_changes_on_mutation"),
        (3, "repeated_summary_is_cached"), (4, "mutation_invalidates_summary"),
        (5, "categories_have_independent_summaries"), (6, "search_normalizes_case_and_space"),
        (7, "decimal_aggregation_is_exact"), (8, "report_composes_stable_catalogue_and_summary"),
    )),
    "R2_api_compat": tuple(f"test_c{i}_{name}" for i, name in (
        (1, "legacy_shape_and_defaults"), (2, "request_timeout_override"),
        (3, "non_idempotent_requests_do_not_retry"), (4, "factory_propagates_options"),
        (5, "existing_constructor_patterns_remain_compatible"), (6, "codec_round_trip_preserves_policy"),
        (7, "batch_preserves_input_order"), (8, "report_composes_response_metadata"),
    )),
    "R3_scientific_pipeline": tuple(f"test_c{i}_{name}" for i, name in (
        (1, "schema_and_row_retention"), (2, "numeric_values_preserve_fraction"),
        (3, "within_group_chronology"), (4, "split_is_group_disjoint"),
        (5, "split_retains_each_row_once"), (6, "split_is_deterministic"),
        (7, "input_order_and_quality_are_stable"), (8, "report_schema_and_partition_counts"),
    )),
    "R4_config_state": tuple(f"test_c{i}_{name}" for i, name in (
        (1, "precedence_across_sources"), (2, "false_and_zero_values_are_preserved"),
        (3, "values_are_typed"), (4, "users_are_isolated"),
        (5, "active_user_and_reset"), (6, "serialization_restores_all_state"),
        (7, "restored_state_can_switch_and_reset"), (8, "report_preserves_policy_and_session_summary"),
    )),
}


def _result(name: str, passed: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def _safe_detail(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    text = re.sub(r"/(?:home|tmp)/[^\s']+", "<path>", text)
    return text[:400]


def _purge_workspace_modules(workspace: Path) -> None:
    root = workspace.resolve()
    for name, module in list(sys.modules.items()):
        module_path = getattr(module, "__file__", None)
        if not module_path:
            continue
        try:
            Path(module_path).resolve().relative_to(root)
        except (OSError, ValueError):
            continue
        sys.modules.pop(name, None)


def _visible_tests(workspace: Path) -> dict[str, Any]:
    env = {**os.environ, "PYTHONPATH": str(workspace)}
    try:
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=workspace, env=env, text=True, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"passed": False, "returncode": None, "stdout": "", "stderr": _safe_detail(exc)}
    return {"passed": result.returncode == 0, "returncode": result.returncode, "stdout": result.stdout[-3000:], "stderr": result.stderr[-3000:]}


def visible_check_vector(workspace: Path, family: str) -> list[bool]:
    """Run each public check independently, preserving its eight-result shape."""
    env = {**os.environ, "PYTHONPATH": str(workspace)}
    values = []
    for method in CHECK_METHODS[family]:
        try:
            result = subprocess.run([sys.executable, "-m", "unittest", f"tests.test_contract.ContractTests.{method}"], cwd=workspace, env=env, text=True, capture_output=True, timeout=30)
            values.append(result.returncode == 0)
        except (OSError, subprocess.TimeoutExpired):
            values.append(False)
    return values


def _r1(workspace: Path) -> list[Callable[[], Any]]:
    def service():
        from inventory.service import InventoryService
        return InventoryService(workspace / "data/items.json")
    def c1():
        from decimal import Decimal
        return service().repository.all_items()[0].amount == Decimal("4.25")
    def c2():
        value = service(); before = value.repository.version; value.replace_amount("A-10", Decimal("8.50")); return value.repository.version > before
    def c3():
        value = service(); value.summary("tools"); before = value.cache.parse_count; value.summary("tools"); return value.cache.parse_count == before
    def c4():
        value = service(); before = value.summary("tools")["total"]; value.replace_amount("A-10", Decimal("8.50")); return value.summary("tools")["total"] != before
    def c5():
        value = service(); tools = value.summary("tools"); parts = value.summary("parts"); return tools["category"] != parts["category"] and value.summary("tools") == tools
    def c6():
        return {item.sku for item in service().search(" alpha ")} == {"A-10", "A-2"}
    def c7():
        from decimal import Decimal
        return service().summary("tools")["total"] == Decimal("6.00")
    def c8():
        value = service(); report = value.report("BETA", "parts"); return report["skus"] == ["A-2", "A-10", "B-3", "B-12"] and report["matches"] == ["B-3", "B-12"] and report["summary"]["total"] == Decimal("5.75")
    return [c1, c2, c3, c4, c5, c6, c7, c8]


def _r2(workspace: Path) -> list[Callable[[], Any]]:
    def c1():
        from clientkit.client import Client
        from clientkit.legacy import old_client
        value = old_client("https://example.test"); return isinstance(value, Client) and (value.timeout, value.retries) == (30, 2)
    def c2():
        from clientkit.client import Client
        return Client("x").request("/a", timeout=7).timeout == 7
    def c3():
        from clientkit.client import Client
        return Client("x", retries=3).request("/write", idempotent=False).attempts == 1
    def c4():
        from clientkit.factory import make_client
        value = make_client("x", timeout=11, retries=4); return (value.timeout, value.retries) == (11, 4)
    def c5():
        from clientkit.client import Client
        from clientkit.legacy import old_client
        value = Client("x", 9, 1); return value.request("/a").timeout == 9 and old_client("x", 8, 0).timeout == 8
    def c6():
        from clientkit.client import Client
        from clientkit.codec import decode, encode
        return decode(encode(Client("x", timeout=13, retries=5))) == {"base_url": "x", "timeout": 13, "retries": 5}
    def c7():
        from clientkit.client import Client
        return [r.path for r in Client("x").request_many(["/b", "/a"])] == ["/b", "/a"]
    def c8():
        from clientkit.report import summarize
        from clientkit.types import Response
        return summarize([Response("/a", 1, 3), Response("/b", 2, 4)]) == {"paths": ["/a", "/b"], "attempts": 3}
    return [c1, c2, c3, c4, c5, c6, c7, c8]


def _r3(workspace: Path) -> list[Callable[[], Any]]:
    def result():
        from experiment.pipeline import run
        return run(workspace / "data/measurements.csv", seed=1)
    def c1():
        rows = result()["rows"]; return len(rows) == 9 and {r.group for r in rows} == {"north", "south", "east"}
    def c2():
        metrics = result()["metrics"]; return abs(metrics["total"] - 49.0) < 1e-9 and abs(metrics["mean"] - 49.0 / 9.0) < 1e-9
    def c3():
        rows = result()["rows"]; return all([r.timestamp for r in rows if r.group == group] == sorted(r.timestamp for r in rows if r.group == group) for group in {"north", "south", "east"})
    def c4():
        value = result(); train = {r.group for r in value["train"]}; evaluation = {r.group for r in value["evaluation"]}; return train.isdisjoint(evaluation)
    def c5():
        value = result(); return sorted(value["train"] + value["evaluation"], key=lambda r: (r.group, r.timestamp)) == value["rows"]
    def c6():
        from experiment.pipeline import run
        value = result(); again = run(workspace / "data/measurements.csv", seed=1); return value["train"] == again["train"] and value["evaluation"] == again["evaluation"]
    def c7():
        rows = result()["rows"]; return rows[0].group == "east" and {r.quality for r in rows} == {"ok"}
    def c8():
        value = result(); report = value["report"]; return report["schema"] == "experiment-v1" and report["train"] + report["evaluation"] == 9 and set(report["train_groups"]) | set(report["evaluation_groups"]) == {"east", "north", "south"}
    return [c1, c2, c3, c4, c5, c6, c7, c8]


def _r4(workspace: Path) -> list[Callable[[], Any]]:
    def service():
        from settings.service import SettingsService
        return SettingsService()
    def c1():
        import json, tempfile
        value = service()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as handle:
            json.dump({"limit": 2, "mode": "file"}, handle); handle.flush(); result = value.load(handle.name, {"APP_LIMIT": "4"}, ["--limit=6"])
        return result == {"enabled": False, "limit": 6, "mode": "file"}
    def c2():
        return service().load(environ={"APP_ENABLED": "false", "APP_LIMIT": "0"}) == {"enabled": False, "limit": 0, "mode": "safe"}
    def c3():
        result = service().load(environ={"APP_ENABLED": "true", "APP_LIMIT": "3"}); return result["enabled"] is True and result["limit"] == 3
    def c4():
        value = service(); ada = value.sessions.activate("ada"); value.sessions.touch(); lin = value.sessions.activate("lin"); return ada["visits"] == 1 and lin["visits"] == 0
    def c5():
        value = service(); value.sessions.activate("ada"); value.sessions.reset(); return value.sessions.active_user is None
    def c6():
        value = service(); value.sessions.activate("ada"); value.sessions.touch(); value.sessions.activate("lin"); encoded = value.save_sessions(); other = service(); other.restore_sessions(encoded); return other.sessions.export() == value.sessions.export()
    def c7():
        value = service(); value.sessions.activate("ada"); other = service(); other.restore_sessions(value.save_sessions()); other.sessions.activate("lin"); other.sessions.reset(); return other.sessions.active_user is None and "ada" in other.sessions.export()["users"]
    def c8():
        from settings.report import describe
        value = service(); value.sessions.activate("ada"); result = value.load(environ={"APP_LIMIT": "0"}); return describe(result, value.sessions) == {"settings": result, "active_user": "ada", "users": ["ada"]}
    return [c1, c2, c3, c4, c5, c6, c7, c8]


def evaluate(instance: TaskInstance, workspace: Path) -> dict[str, Any]:
    workspace_text = str(workspace)
    sys.path.insert(0, workspace_text)
    try:
        builders = {"R1_maintenance": _r1, "R2_api_compat": _r2, "R3_scientific_pipeline": _r3, "R4_config_state": _r4}
        checks = []
        for index, check in enumerate(builders[instance.family](workspace), 1):
            try:
                outcome = check()
                passed, detail = (outcome, "") if isinstance(outcome, bool) else (bool(outcome), "")
                checks.append(_result(f"C{index}", passed, detail))
            except Exception as exc:
                checks.append(_result(f"C{index}", False, _safe_detail(exc)))
    finally:
        if sys.path and sys.path[0] == workspace_text:
            sys.path.pop(0)
        _purge_workspace_modules(workspace)
    if len(checks) != 8:
        raise ValueError(f"malformed evaluator vector: expected 8, got {len(checks)}")
    passed = sum(item["passed"] for item in checks)
    visible = _visible_tests(workspace)
    return {"evaluation_class": "public_characterization", "objective": True, "adversarial_isolation": False, "authoritative_reference_present": False, "checks": checks, "check_vector": [item["passed"] for item in checks], "score": 100.0 * passed / 8.0, "maximum": 100.0, "full_pass": passed == 8, "public_tests": visible, "scope_compliance": True, "visible_evaluator_only": True}
