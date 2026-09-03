from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
import struct
from pathlib import Path
from typing import Any


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _result(score: float, maximum: float, notes: list[str]) -> dict[str, Any]:
    return {"score": score, "maximum": maximum, "notes": notes}


def _diagnostic_plot_score(workspace: Path) -> dict[str, Any]:
    """Evaluate the artifact directly, without unittest discovery.

    The old path coupled an artifact task to a candidate ``tests`` package;
    namespace-package/disposable-workspace execution made that evaluator fail
    before scoring.  Artifact validity is now checked from bytes and JSON.
    """
    image, summary = workspace / "diagnostic.png", workspace / "summary.json"
    notes: list[str] = []
    score = 0.0
    raw = image.read_bytes() if image.is_file() else b""
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        score += 1; notes.append("valid PNG signature")
        if len(raw) >= 24 and raw[12:16] == b"IHDR":
            width, height = struct.unpack(">II", raw[16:24])
            if width > 0 and height > 0:
                notes.append(f"PNG dimensions {width}x{height}")
    else:
        notes.append("diagnostic.png missing or invalid")
    if summary.is_file():
        try:
            data = _json(summary)
            if data.get("outlier_sample") == "S08": score += 1
            if data.get("outlier_reason") == "low_library_size": score += 1
        except (OSError, ValueError, TypeError) as exc:
            notes.append(f"summary.json invalid: {exc}")
    else:
        notes.append("summary.json missing")
    return _result(score, 3, notes)


def evaluate(task_id: str, workspace: Path, root: Path) -> dict[str, Any]:
    if task_id == "research_python":
        path = workspace / "answer.json"
        if not path.exists(): return _result(0, 5, ["answer.json is missing"])
        try: answer = _json(path)
        except Exception as exc: return _result(0, 5, [f"invalid JSON: {exc}"])
        expected = {"n": 12, "mean_response": 15.25, "control_mean": 12.0, "treatment_mean": 18.5, "difference": 6.5}
        score = sum(answer.get(k) == v for k, v in expected.items())
        return _result(float(score), 5, ["exact fields matched: " + str(score) + "/5"])
    if task_id == "diagnostic_plot":
        return _diagnostic_plot_score(workspace)
    if task_id == "debug_package":
        # Evaluation never writes bytecode or other artifacts into the contestant output.
        with tempfile.TemporaryDirectory(prefix="benchmark-eval-") as temporary:
            evaluation_copy = Path(temporary) / "workspace"
            shutil.copytree(workspace, evaluation_copy)
            result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=evaluation_copy, text=True, capture_output=True)
        return _result(5.0 if result.returncode == 0 else 0.0, 5, [result.stdout[-1000:], result.stderr[-1000:]])
    if task_id == "repository_review":
        report = workspace / "REVIEW.md"
        if not report.exists(): return _result(0, 4, ["REVIEW.md is missing"])
        text = report.read_text().lower()
        manifest = _json(root / "private_admin/manifests/repository_review.json")
        hits = [item["id"] for item in manifest["issues"] if all(word in text for word in item["keywords"])]
        return _result(float(len(hits)), 4, ["matched hidden issue ids: " + ", ".join(hits)])
    if task_id == "pandoc_pdf":
        path = workspace / "report.pdf"
        valid = path.exists() and path.read_bytes().startswith(b"%PDF")
        return _result(2.0 if valid else 0.0, 2, ["valid PDF header" if valid else "report.pdf missing or invalid"])
    if task_id == "scientific_writing":
        path = workspace / "RESULTS_DISCUSSION.md"
        if not path.exists(): return _result(0, 4, ["RESULTS_DISCUSSION.md is missing"])
        text = path.read_text().lower()
        terms = ["results", "discussion", "18.4", "12.1", "0.003", "limitation"]
        hits = sum(term in text for term in terms)
        return _result(float(hits), 6, [f"required evidence/rubric tokens: {hits}/6"])
    raise ValueError(task_id)
