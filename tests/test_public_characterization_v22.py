import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from benchmark.public_characterization_v22 import CALIBRATION_SEED, EVALUATION_SEEDS, FAMILIES, PHASE_CALIBRATION
from benchmark.public_characterization_v22.evaluate import evaluate
from benchmark.public_characterization_v22.generate import make_instance, materialize
from benchmark.public_characterization_v22.gold_accessibility import audit_tracked_gold_accessibility
from benchmark.public_characterization_v22.runner import _calibration_useful, prohibited_files


class PublicCharacterizationV22Tests(unittest.TestCase):
    def test_generation_is_deterministic_and_seed_spaces_are_disjoint(self):
        for i, family in enumerate(FAMILIES):
            a = make_instance(family, CALIBRATION_SEED + i)
            b = make_instance(family, CALIBRATION_SEED + i)
            self.assertEqual(a.files, b.files)
            self.assertNotEqual(a.seed, EVALUATION_SEEDS[family])

    def test_baselines_have_headroom_and_visible_parity(self):
        for i, family in enumerate(FAMILIES):
            with tempfile.TemporaryDirectory() as temporary:
                instance = make_instance(family, CALIBRATION_SEED + i)
                workspace = materialize(instance, Path(temporary) / family)
                controller = evaluate(instance, workspace)
                visible = subprocess.run([sys.executable, str(workspace / "verifier/verify.py")], cwd=workspace, capture_output=True, text=True, check=False)
                self.assertEqual(controller["score"], 37.5 if i == 0 else 25.0)
                self.assertEqual(controller["check_vector"], json.loads(visible.stdout)["checks"])
                self.assertEqual(len(controller["check_vector"]), 8)

    def test_generated_artifacts_are_ignored_but_data_is_immutable(self):
        instance = make_instance("P1_stateful_inventory", CALIBRATION_SEED)
        self.assertEqual(prohibited_files(["data/items.json", "__pycache__/x.pyc", "app/x.py"], instance.edit_scope), ["data/items.json"])

    def test_gold_accessibility_gate_has_no_answer_bearing_source(self):
        result = audit_tracked_gold_accessibility(Path(__file__).resolve().parents[1])
        self.assertEqual(result["status"], "pass")
        self.assertFalse(result["answer_bearing_repair_procedure"])

    def test_calibration_useful_requires_intermediate_non_full_results(self):
        base = {"status": "completed", "baseline_score": 25.0, "final_score": 75.0}
        self.assertTrue(_calibration_useful([base, {**base, "final_score": 62.5}]))
        self.assertFalse(_calibration_useful([base, {**base, "final_score": 100.0}]))

