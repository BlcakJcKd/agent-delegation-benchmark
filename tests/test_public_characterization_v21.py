import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark.public_characterization_v21 import FAMILIES, PHASE_A_FAMILIES, PHASE_B_FAMILIES
from benchmark.public_characterization_v21.evaluate import evaluate, run_checks
from benchmark.public_characterization_v21.generate import make_instance, materialize
from benchmark.public_characterization_v21.runner import _discriminates, prohibited_files, validate_preflight
from benchmark.review_bundle import create_review_bundle


class PublicCharacterizationV21Tests(unittest.TestCase):
    def test_every_baseline_and_visible_verifier_has_exactly_eight_checks(self):
        import subprocess
        for index, family in enumerate(FAMILIES):
            instance = make_instance(family, 20261101 + index)
            with tempfile.TemporaryDirectory() as temporary:
                workspace = materialize(instance, Path(temporary))
                controller = evaluate(instance, workspace)
                visible = subprocess.run(["python", "verifier/verify.py"], cwd=workspace, text=True, capture_output=True, check=False)
                payload = json.loads(visible.stdout)
                self.assertEqual(len(controller["check_vector"]), 8)
                self.assertEqual(len(payload["checks"]), 8)
                self.assertEqual(controller["check_vector"], payload["checks"])

    def test_check_exception_isolation(self):
        checks = run_checks([(f"c{i}", (lambda: (_ for _ in ()).throw(RuntimeError("boom"))) if i == 3 else (lambda: True)) for i in range(8)])
        self.assertEqual(len(checks), 8)
        self.assertFalse(checks[3]["passed"])
        self.assertTrue(all(checks[i]["passed"] for i in range(8) if i != 3))

    def test_p4_contract_requires_non_default_codec_round_trip(self):
        contract = make_instance("P4_compatibility", 20261104).files["verifier/contract.py"]
        self.assertIn("timeout':9", contract)

    def test_p1_and_p3_fixture_data_are_immutable(self):
        for family in ("P1_multi_file_state", "P3_scientific_pipeline"):
            instance = make_instance(family, 20261101 if family.startswith("P1") else 20261103)
            self.assertIn("data/**", instance.edit_scope["immutable"])
            self.assertEqual(prohibited_files(["data/items.json", "data/measurements.csv"], instance.edit_scope), ["data/items.json", "data/measurements.csv"])

    def test_phase_families_are_exactly_six_attempts_each(self):
        self.assertEqual(len(PHASE_A_FAMILIES) * 3, 6)
        self.assertEqual(len(PHASE_B_FAMILIES) * 3, 6)

    def test_phase_gate_ignores_latency_and_requires_behavioral_difference(self):
        rows = [{"status": "completed", "final_score": 100.0, "final_check_vector": [True] * 8, "full_pass": True} for _ in range(6)]
        rows[0]["wall_seconds"] = 1.0
        rows[1]["wall_seconds"] = 2.0
        self.assertFalse(_discriminates(rows))

    def test_preflight_requires_reference_metadata_without_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch("benchmark.public_characterization_v21.runner.state_root", return_value=Path(temporary)), patch("benchmark.public_characterization_v21.runner.validate_git_identity", return_value={"git_sha": "test"}):
                result = validate_preflight(require_reference=True)
        self.assertFalse(result["ok"])
        self.assertFalse(result["gates"]["reference_validation"])

    def test_bundle_includes_public_baseline_snapshots_but_not_workspaces(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"; (state / "evidence").mkdir(parents=True)
            (state / "run-summary.json").write_text(json.dumps({"evaluation_class": "public_characterization"}))
            (state / "baseline-task-snapshots/P1/app/store.py").parent.mkdir(parents=True)
            (state / "baseline-task-snapshots/P1/app/store.py").write_text("public synthetic source")
            (state / "workspaces/P1/app/store.py").parent.mkdir(parents=True)
            (state / "workspaces/P1/app/store.py").write_text("candidate source")
            result = create_review_bundle("public-characterization-v2.1", state_dir=state, output=Path(temporary) / "bundle")
            bundle = Path(result["bundle"])
            self.assertTrue((bundle / "baseline-task-snapshots/P1/app/store.py").is_file())
            self.assertFalse((bundle / "workspaces").exists())


if __name__ == "__main__":
    unittest.main()
