"""Pre-inference validation gate for Benchmark V2."""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from . import CODING_FAMILIES, SCHEMA_VERSION
from .evaluate import evaluate, reference_fix
from .generate import make_instance, materialize, workspace_digest


def _hash_tree(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        h.update(path.relative_to(root).as_posix().encode()); h.update(path.read_bytes())
    return h.hexdigest()


def validate(root: Path, seed: int = 20260903) -> dict[str, object]:
    results = []
    with tempfile.TemporaryDirectory(prefix="benchmark-v2-validation-") as d:
        base = Path(d)
        for index, family in enumerate(CODING_FAMILIES):
            instance = make_instance(family, seed + index)
            candidate = base / family
            materialize(instance, candidate)
            before = evaluate(instance, candidate, base / "hidden-evaluator")
            broken_fails = before["correctness"] < 100
            digest_a = workspace_digest(candidate)
            reference_fix(instance, candidate)
            after = evaluate(instance, candidate, base / "hidden-evaluator")
            candidate2 = base / (family + "-repeat")
            materialize(instance, candidate2)
            digest_b = workspace_digest(candidate2)
            hidden = base / "hidden-evaluator"
            hidden.mkdir(mode=0o700, exist_ok=True)
            (hidden / "expected_solution.py").write_text("private")
            results.append({"family": family, "broken_initial_fails": broken_fails, "reference_passes": after["correctness"] == 100, "reproducible": digest_a == digest_b, "isolation": after["hidden_evaluator_outside_candidate"], "broken_score": before["correctness"], "fixed_score": after["correctness"]})
    ok = all(all(item[k] for k in ("broken_initial_fails", "reference_passes", "reproducible", "isolation")) for item in results)
    return {"schema_version": SCHEMA_VERSION, "ok": ok, "results": results, "test_count": len(results)}


def frozen_manifest(root: Path, seed: int = 20260903) -> dict[str, object]:
    """Return hashes for the frozen public task generator and evaluator code."""
    package = Path(__file__).parent
    return {"schema_version": SCHEMA_VERSION, "seed": seed, "task_families": {family: {"candidate_hash": _hash_tree(package), "family": family} for family in CODING_FAMILIES}, "evaluator_hash": hashlib.sha256(Path(__file__).with_name("evaluate.py").read_bytes()).hexdigest()}

