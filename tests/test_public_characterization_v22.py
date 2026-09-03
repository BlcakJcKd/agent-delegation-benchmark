import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from benchmark.public_characterization_v22 import ATTEMPT_TIMEOUT_SECONDS, CALIBRATION_SEED, EVALUATION_SEEDS, FAMILIES, PHASE_CALIBRATION
from benchmark.public_characterization_v22.evaluate import evaluate
from benchmark.public_characterization_v22.generate import make_instance, materialize
from benchmark.public_characterization_v22.gold_accessibility import audit_tracked_gold_accessibility
from benchmark.public_characterization_v22.runner import ROOT_CLUSTERS, _calibration_stop_reason, _calibration_useful, prohibited_files
from benchmark.review_bundle import create_review_bundle


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
                self.assertEqual(controller["score"], 12.5)
                self.assertEqual(controller["check_vector"], json.loads(visible.stdout)["checks"])
                self.assertEqual(len(controller["check_vector"]), 8)

    def test_generated_artifacts_are_ignored_but_data_is_immutable(self):
        instance = make_instance("P1_stateful_inventory", CALIBRATION_SEED)
        self.assertEqual(prohibited_files(["data/items.json", "__pycache__/x.pyc", "app/x.py"], instance.edit_scope), ["data/items.json", "app/x.py"])

    def test_gold_accessibility_gate_has_no_answer_bearing_source(self):
        result = audit_tracked_gold_accessibility(Path(__file__).resolve().parents[1])
        self.assertEqual(result["status"], "pass")
        self.assertFalse(result["answer_bearing_repair_procedure"])

    def test_calibration_useful_requires_intermediate_non_full_results(self):
        base = {"status": "completed", "baseline_score": 25.0, "final_score": 75.0}
        self.assertTrue(_calibration_useful([base, {**base, "final_score": 62.5}]))
        self.assertFalse(_calibration_useful([base, {**base, "final_score": 100.0}]))
        self.assertEqual(_calibration_stop_reason({**base, "final_score": 100.0}), "calibration_task_saturated")
        self.assertEqual(_calibration_stop_reason({**base, "final_score": 25.0}), "calibration_no_improvement")

    def test_structural_metadata_has_four_clusters_per_family(self):
        self.assertTrue(all(len(clusters) >= 4 for clusters in ROOT_CLUSTERS.values()))

    def test_fixed_operational_budget_and_phase_seed_separation(self):
        self.assertEqual(ATTEMPT_TIMEOUT_SECONDS, 900)
        self.assertNotIn(CALIBRATION_SEED, EVALUATION_SEEDS.values())

    def test_bundle_allowlists_calibration_evidence_and_excludes_workspaces(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            state.mkdir()
            (state / "REPORT.md").write_text("report")
            (state / "calibration-evidence").mkdir()
            (state / "calibration-evidence" / "P1.json").write_text("{}")
            (state / "workspaces").mkdir()
            (state / "workspaces" / "secret.txt").write_text("not included")
            result = create_review_bundle("public-characterization-v2.2", state_dir=state, output=Path(temporary) / "bundle")
            self.assertIn("calibration-evidence/P1.json", result["manifest"]["included_files"])
            self.assertEqual(result["manifest"]["attempts"], 1)
            self.assertEqual(result["manifest"]["completed"], 0)
            self.assertFalse(any("workspaces" in name for name in result["manifest"]["included_files"]))
