"""Shared validation metadata semantics for characterization suites."""
from __future__ import annotations

from typing import Any


def reference_task_status(
    task: dict[str, Any],
    reference: dict[str, Any] | None,
    *,
    suite: str,
    version: str,
    seed: int,
    suite_git_sha: str | None,
    check_count: int,
) -> bool | None:
    """Return pending, passed, or failed without conflating pending and false."""
    if reference is None:
        return None
    if not reference.get("passed"):
        return False
    if (
        reference.get("suite") != suite
        or reference.get("version") != version
        or reference.get("seed") != seed
        or reference.get("suite_git_sha") != suite_git_sha
    ):
        return False
    item = next((x for x in reference.get("tasks", []) if x.get("family") == task.get("family")), None)
    return bool(
        item
        and item.get("score") == 100.0
        and item.get("check_vector") == [True] * check_count
        and item.get("visible_check_vector") == [True] * check_count
    )


def propagate_reference_status(
    tasks: list[dict[str, Any]],
    reference: dict[str, Any] | None,
    *,
    suite: str,
    version: str,
    seed: int,
    suite_git_sha: str | None,
    check_count: int,
) -> bool | None:
    statuses = []
    for task in tasks:
        status = reference_task_status(
            task,
            reference,
            suite=suite,
            version=version,
            seed=seed,
            suite_git_sha=suite_git_sha,
            check_count=check_count,
        )
        task["reference_validation_passed"] = status
        statuses.append(status)
    if reference is None:
        return None
    return bool(statuses) and all(status is True for status in statuses)


def validation_consistency(
    result: dict[str, Any],
    *,
    reference_required: bool,
    check_count: int,
) -> dict[str, Any]:
    """Check that global and task-level validation states agree."""
    tasks = result.get("tasks", [])
    ref = result.get("reference_validation")
    global_state = result.get("gates", {}).get("reference_validation")
    task_states = [task.get("reference_validation_passed") for task in tasks]
    if reference_required and ref is None:
        return {"ok": False, "reason": "reference_validation_missing"}
    if ref is None:
        return {"ok": global_state in (None, "not_required") and all(x is None for x in task_states), "reason": "pending"}
    expected = global_state is True
    task_ok = all(x is expected for x in task_states)
    vectors_ok = all(
        len(task.get("baseline_check_vector", [])) == check_count
        for task in tasks
    )
    return {"ok": task_ok and vectors_ok and (not expected or ref.get("passed") is True), "reason": "consistent" if task_ok else "task_global_mismatch"}
