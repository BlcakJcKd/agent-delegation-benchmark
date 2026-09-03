import json
import inspect
import tempfile
import unittest
from pathlib import Path

from benchmark.public_characterization_v23 import CALIBRATION_SEED, EVALUATION_SEED
from benchmark.public_characterization_v23.evaluate import evaluate
from benchmark.public_characterization_v23.generate import make_instance, materialize, workspace_digest
from benchmark.public_characterization_v23.gold_accessibility import audit_tracked_gold_accessibility
from benchmark.public_characterization_v23.runner import FEATURE_CLUSTERS, _calibration_useful, _sloc_and_graph, pilot, prohibited_files
from benchmark.review_bundle import create_review_bundle


class PublicCharacterizationV23Tests(unittest.TestCase):
    def test_generation_is_deterministic_and_seeds_are_separate(self):
        first = make_instance("P1_snapshot_inventory", CALIBRATION_SEED)
        second = make_instance("P1_snapshot_inventory", CALIBRATION_SEED)
        evaluation = make_instance("P1_snapshot_inventory", EVALUATION_SEED)
        self.assertEqual(first.files, second.files)
        self.assertEqual(first.prompt, second.prompt)
        self.assertNotEqual(first.task_id, evaluation.task_id)
        with tempfile.TemporaryDirectory() as temp:
            a, b = Path(temp) / "a", Path(temp) / "b"
            materialize(first, a)
            materialize(second, b)
            self.assertEqual(workspace_digest(a), workspace_digest(b))

    def test_old_contract_and_new_headroom_are_separate(self):
        instance = make_instance("P1_snapshot_inventory", CALIBRATION_SEED)
        with tempfile.TemporaryDirectory() as temp:
            root = materialize(instance, Path(temp) / "task")
            result = evaluate(instance, root)
        self.assertTrue(result["old_contract_tests_passed_after"])
        self.assertEqual(result["old_contract_regressions"], 0)
        self.assertEqual(result["check_vector"], [False] * 8)
        self.assertEqual(result["new_feature_score"], 0.0)
        self.assertFalse(result["full_pass"])

    def test_visible_contract_has_eight_independent_named_checks(self):
        instance = make_instance("P1_snapshot_inventory", CALIBRATION_SEED)
        contract = instance.files["verifier/contract.py"]
        self.assertEqual(contract.count("_safe("), 9)
        self.assertEqual(contract.count("return [_safe"), 1)
        self.assertEqual(len(FEATURE_CLUSTERS), 5)
        self.assertEqual(len({item["id"] for item in FEATURE_CLUSTERS}), 5)

    def test_surface_and_edit_scope_gate(self):
        instance = make_instance("P1_snapshot_inventory", CALIBRATION_SEED)
        surface = _sloc_and_graph(instance)
        self.assertGreaterEqual(surface["substantive_sloc"], 250)
        self.assertLessEqual(surface["substantive_sloc"], 600)
        self.assertGreaterEqual(surface["meaningful_module_count"], 8)
        self.assertLessEqual(surface["meaningful_module_count"], 15)
        self.assertEqual(prohibited_files(["inventory/service.py", "data/products.json", "tests/test_contract.py", "__pycache__/x.pyc"], instance.edit_scope), ["data/products.json", "tests/test_contract.py"])

    def test_issue_style_spec_does_not_reveal_patch_recipe(self):
        instance = make_instance("P1_snapshot_inventory", CALIBRATION_SEED)
        readme = instance.files["README.md"]
        self.assertIn("stable, named view", readme)
        self.assertNotIn("change the cache key", readme.lower())
        self.assertNotIn("modify inventory/", readme.lower())

    def test_calibration_gate_excludes_saturated_or_unchanged_results(self):
        base = {"status": "completed", "baseline_score": 0.0, "old_contract_regressions": 0, "full_pass": False}
        self.assertFalse(_calibration_useful([{**base, "final_score": 100.0}]))
        self.assertFalse(_calibration_useful([{**base, "final_score": 0.0}]))
        self.assertTrue(_calibration_useful([{**base, "final_score": 62.5}]))

    def test_pilot_is_calibration_only_until_separate_authorization(self):
        source = inspect.getsource(pilot)
        self.assertIn('"comparative_authorized": False', source)
        self.assertNotIn("eval_gate", source)
        self.assertNotIn("for model, reasoning in COMPARISON_CONFIGURATIONS", source)

    def test_gold_accessibility_has_no_tracked_repair_material(self):
        result = audit_tracked_gold_accessibility(Path(__file__).resolve().parents[1])
        self.assertEqual(result["status"], "pass")
        self.assertFalse(result["answer_bearing_repair_procedure"])

    def test_public_bundle_includes_baseline_snapshot_but_excludes_private_material(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / "state"
            (state / "baseline-task-snapshots/P1_snapshot_inventory").mkdir(parents=True)
            (state / "evidence").mkdir()
            (state / "run-summary.json").write_text(json.dumps({"evaluation_class": "public_characterization"}))
            (state / "REPORT.md").write_text("report\n")
            (state / "baseline-task-snapshots/P1_snapshot_inventory/README.md").write_text("public\n")
            (state / "evidence/a.json").write_text("{}\n")
            (state / "ledger.sqlite3").write_text("private\n")
            (state / "workspaces").mkdir()
            result = create_review_bundle("public-characterization-v2.3", state_dir=state, output=Path(temp) / "bundle")
            bundle = Path(result["bundle"])
            self.assertTrue((bundle / "baseline-task-snapshots/P1_snapshot_inventory/README.md").is_file())
            self.assertFalse((bundle / "ledger.sqlite3").exists())
            self.assertFalse((bundle / "workspaces").exists())
            self.assertFalse(result["manifest"]["credentials_included"])


if __name__ == "__main__":
    unittest.main()
