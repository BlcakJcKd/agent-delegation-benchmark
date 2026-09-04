"""Controller-side audit that no reference implementation is tracked."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


_FORBIDDEN_MARKERS = (
    "reference_solution_source",
    "gold_implementation_source",
    "repair_writer_script",
    "answer_bearing_repair_source",
)


def _tracked_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=repo_root, capture_output=True, text=True, check=False,
    )
    return sorted(line for line in result.stdout.splitlines() if line)


def audit_tracked_gold_accessibility(repo_root: Path) -> dict[str, Any]:
    """Conservatively detect retained answer-writer artifacts.

    Feature requirements and verifier code are intentionally allowed.  The
    marker set is limited to names that describe a repair writer or retained
    reference artifact, avoiding a blanket ban on normal unsupported behavior.
    """
    findings: list[dict[str, str]] = []
    for relative in _tracked_files(repo_root):
        path = repo_root / relative
        if not path.is_file() or path.name == "gold_accessibility.py":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lower = text.casefold()
        for marker in _FORBIDDEN_MARKERS:
            if marker.casefold() in lower:
                findings.append({"file": relative, "detail": f"repair artifact marker: {marker}"})
                break
    return {
        "status": "pass" if not findings else "fail",
        "findings": findings[:40],
        "tracked_source_scanned": True,
        "reference_source_retained": False,
        "temporary_reference_repair_required": True,
    }


def validate_clean_reference_state(paths: list[Path]) -> dict[str, Any]:
    """Validate that ephemeral reference paths no longer exist."""
    remaining = [str(path) for path in paths if path.exists()]
    return {"status": "pass" if not remaining else "fail", "remaining_paths": remaining}
