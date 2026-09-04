"""No-inference quality gates for repository-scale V2.4 tasks."""
from __future__ import annotations

import fnmatch
import re
import subprocess
from pathlib import Path
from typing import Any

from . import FEATURE_CLUSTERS, FEATURE_VOCABULARY


def _match(path: str, pattern: str) -> bool:
    return fnmatch.fnmatch(path, pattern) or ("**/" in pattern and fnmatch.fnmatch(path, pattern.replace("**/", "")))


def prohibited_files(changes: list[str], scope: dict[str, Any]) -> list[str]:
    ignored = {"__pycache__", ".pytest_cache"}
    return [path for path in changes if not any(part in ignored for part in Path(path).parts) and Path(path).suffix != ".pyc" and not any(_match(path, pattern) for pattern in scope.get("editable", []))]


def surface_metrics(files: dict[str, str]) -> dict[str, Any]:
    modules: list[str] = []
    sloc = 0
    graph: dict[str, list[str]] = {}
    for name, source in files.items():
        if not name.endswith(".py") or name.startswith(("tests/", "verifier/")) or Path(name).name == "__init__.py":
            continue
        modules.append(name[:-3].replace("/", "."))
        lines = [line for line in source.splitlines() if line.strip() and not line.lstrip().startswith("#")]
        sloc += len(lines)
        graph[name] = [line.strip() for line in lines if line.strip().startswith(("from ", "import "))]
    return {"substantive_sloc": sloc, "meaningful_module_count": len(modules), "dependency_graph": graph}


def _feature_re(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


def feature_scaffolding_leakage(instance: Any) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    vocabulary = [re.escape(word) for word in FEATURE_VOCABULARY]
    feature_re = _feature_re("(?:" + "|".join(vocabulary) + ")")
    marker_re = _feature_re(r"(?:TODO|FIXME|NotImplementedError|UnsupportedFeature|pass\s*#?)")
    for name, source in instance.files.items():
        if name.startswith(("verifier/", ".ekalavya/", "README.md", "tests/")) or not name.endswith((".py", ".md", ".json")):
            continue
        for lineno, line in enumerate(source.splitlines(), 1):
            if feature_re.search(line) and (marker_re.search(line) or _feature_re(r"(?:class|def|import|from|placeholder|stub|new feature)").search(line)):
                findings.append({"file": name, "line": str(lineno), "detail": "feature-specific scaffold near requested vocabulary"})
    return {"status": "fail" if findings else "pass", "findings": findings[:40]}


def feature_absence_gate(instance: Any, repo_root: Path) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    feature_re = _feature_re("(?:" + "|".join(re.escape(word) for word in FEATURE_VOCABULARY) + ")")
    for name, source in instance.files.items():
        if name.startswith(("verifier/", ".ekalavya/", "README.md", "data/")):
            continue
        if feature_re.search(source):
            findings.append({"file": name, "detail": "requested feature vocabulary present in baseline"})
    # The current committed tree must not already contain this suite's task or
    # a retained solution.  This is a history check, not a provider query.
    try:
        # The generated synthetic application is intentionally not a tracked
        # repository path.  Do not search the V2.4 generator itself: its
        # public contract necessarily contains the requested vocabulary.
        result = subprocess.run(["git", "log", "--all", "-S", "create_bookmark", "--oneline", "--", "dispatchboard"], cwd=repo_root, capture_output=True, text=True, check=False)
        if result.stdout.strip():
            findings.append({"file": "git history", "detail": "feature solution vocabulary found in benchmark history"})
    except OSError:
        findings.append({"file": "git", "detail": "history audit unavailable"})
    return {"status": "fail" if findings else "pass", "findings": findings}


def validate_surface(metrics: dict[str, Any]) -> bool:
    return 800 <= metrics["substantive_sloc"] <= 3000 and 15 <= metrics["meaningful_module_count"] <= 40


def validate_feature_clusters() -> bool:
    return len(FEATURE_CLUSTERS) >= 4 and len({item["id"] for item in FEATURE_CLUSTERS}) == len(FEATURE_CLUSTERS)
