"""Controller-side audit that the tracked V2.2 package contains no gold repair."""
from __future__ import annotations

import subprocess
from pathlib import Path


def audit_tracked_gold_accessibility(repo: Path) -> dict:
    package = Path("benchmark/public_characterization_v22")
    result = subprocess.run(
        ["git", "ls-files", "--", str(package)],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    paths = [Path(x) for x in result.stdout.splitlines() if x]
    suspicious_names = {"gold.py", "reference.py", "repair.py", "solution.py", "gold_patch.py"}
    suspicious = [p.as_posix() for p in paths if p.name.lower() in suspicious_names]
    stale_build = repo / "build/lib/benchmark/public_characterization_v22"
    stale_build_files = sorted(str(p.relative_to(repo)) for p in stale_build.rglob("*") if p.is_file()) if stale_build.is_dir() else []
    return {
        "checked": result.returncode == 0 and bool(paths),
        "tracked_source_count": len(paths),
        "answer_bearing_source_files": suspicious,
        "stale_build_copy_files": stale_build_files,
        "gold_material_paths": [],
        "answer_bearing_repair_procedure": bool(suspicious or stale_build_files),
        "status": "pass" if result.returncode == 0 and bool(paths) and not suspicious and not stale_build_files else "fail",
        "policy": "tracked task generation/evaluation may define behavior but may not contain a complete repair writer",
    }
