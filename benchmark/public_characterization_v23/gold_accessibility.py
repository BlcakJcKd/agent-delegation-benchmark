"""Tracked-source screen for answer-bearing V2.3 repair material."""
from __future__ import annotations

import subprocess
import re
from pathlib import Path


def audit_tracked_gold_accessibility(repo: Path) -> dict:
    package = "benchmark/public_characterization_v23"
    try:
        tracked = subprocess.check_output(["git", "ls-files", package], cwd=repo, text=True).splitlines()
    except (OSError, subprocess.CalledProcessError):
        tracked = []
    suspicious = {"gold.py", "reference.py", "repair.py", "solution.py", "gold_patch.py"}
    source_hits = [name for name in tracked if Path(name).name.lower() in suspicious]
    marker_pattern = re.compile(r"(?i)(?:write[_-]?(?:gold|reference|solution)|answer[_-]?bearing|known[_-]?good[_-]?repair)")
    marker_hits = []
    for name in tracked:
        if name.endswith("/gold_accessibility.py"):
            continue
        path = repo / name
        try:
            if marker_pattern.search(path.read_text(encoding="utf-8")):
                marker_hits.append(name)
        except (OSError, UnicodeDecodeError):
            marker_hits.append(name)
    stale = [str(path.relative_to(repo)) for path in (repo / "build/lib" / package).rglob("*") if path.is_file()] if (repo / "build/lib" / package).is_dir() else []
    return {
        "checked": True,
        "tracked_source_count": len(tracked),
        "answer_bearing_source_files": source_hits,
        "stale_build_copy_files": stale,
        "gold_material_paths": [],
        "answer_bearing_marker_files": marker_hits,
        "answer_bearing_repair_procedure": bool(source_hits or marker_hits or stale),
        "status": "fail" if source_hits or marker_hits or stale else "pass",
        "policy": "tracked baseline/specification/evaluator code may define behavior but may not contain a complete repair writer",
    }
