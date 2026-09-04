import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from benchmark.public_characterization_v24 import ATTEMPT_TIMEOUT_SECONDS, CALIBRATION_SEED, CHECK_COUNT
from benchmark.public_characterization_v24.evaluate import evaluate
from benchmark.public_characterization_v24.generate import make_instance, materialize, workspace_digest
from benchmark.public_characterization_v24.gold_accessibility import audit_tracked_gold_accessibility, validate_clean_reference_state
from benchmark.public_characterization_v24.quality import feature_absence_gate, feature_scaffolding_leakage, prohibited_files, surface_metrics, validate_surface
from benchmark.public_characterization_v24.runner import _report_timeout


class PublicCharacterizationV24Tests(unittest.TestCase):
    def setUp(self):
        self.instance = make_instance("P1_named_report_bookmarks", CALIBRATION_SEED)

    def test_baseline_is_correct_old_contract_with_headroom(self):
        with tempfile.TemporaryDirectory() as directory:
            result = evaluate(self.instance, materialize(self.instance, Path(directory) / "task"))
        self.assertEqual(result["check_vector"], [False] * CHECK_COUNT)
        self.assertEqual(result["new_feature_score"], 0.0)
        self.assertTrue(result["old_contract_tests_passed_after"])

    def test_generation_is_deterministic_and_surface_is_repository_scale(self):
        first = self.instance.files
        second = make_instance("P1_named_report_bookmarks", CALIBRATION_SEED).files
        self.assertEqual(first, second)
        self.assertTrue(validate_surface(surface_metrics(first)))

    def test_feature_is_absent_and_not_scaffolded(self):
        self.assertEqual(feature_absence_gate(self.instance, Path.cwd())["status"], "pass")
        self.assertEqual(feature_scaffolding_leakage(self.instance)["status"], "pass")

    def test_scaffolding_gate_is_relative_to_feature_vocabulary(self):
        files = dict(self.instance.files)
        files["dispatchboard/future.py"] = "class BookmarkUnsupportedFeature: pass\n"
        bad = SimpleNamespace(files=files)
        self.assertEqual(feature_scaffolding_leakage(bad)["status"], "fail")

    def test_exactly_eight_checks_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            result = evaluate(self.instance, materialize(self.instance, Path(directory) / "task"))
        self.assertEqual(len(result["checks"]), CHECK_COUNT)
        self.assertEqual(len(result["check_vector"]), CHECK_COUNT)
        self.assertEqual([item["passed"] for item in result["checks"]], [False] * CHECK_COUNT)
        self.assertTrue(all(item["detail"] == "AttributeError" for item in result["checks"]))

    def test_generated_noise_is_not_scope_tampering(self):
        scope = self.instance.edit_scope
        self.assertEqual(prohibited_files(["__pycache__/x.pyc", ".pytest_cache/a", "dispatchboard/api.py", "tests/x.py"], scope), ["tests/x.py"])

    def test_timeout_report_comes_from_requested_evidence(self):
        rows = [{"requested": {"attempt_timeout_seconds": 420}}, {"requested": {"attempt_timeout_seconds": 420}}]
        self.assertEqual(_report_timeout(rows), 420)
        self.assertEqual(_report_timeout([]), ATTEMPT_TIMEOUT_SECONDS)
        self.assertEqual(_report_timeout([{ "requested": {"attempt_timeout_seconds": 420}}, {"requested": {"attempt_timeout_seconds": 900}}]), ATTEMPT_TIMEOUT_SECONDS)

    def test_gold_accessibility_and_cleanup_contract(self):
        self.assertEqual(audit_tracked_gold_accessibility(Path.cwd())["status"], "pass")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ephemeral-reference"
            self.assertEqual(validate_clean_reference_state([path])["status"], "pass")

    def test_workspace_hash_includes_public_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = materialize(self.instance, Path(directory) / "task")
            before = workspace_digest(root)
            root.joinpath(".pytest_cache").mkdir()
            root.joinpath(".pytest_cache/ignored").write_text("noise")
            root.joinpath("dispatchboard/api.py").write_text(root.joinpath("dispatchboard/api.py").read_text() + "\n")
            self.assertNotEqual(before, workspace_digest(root))


if __name__ == "__main__":
    unittest.main()
