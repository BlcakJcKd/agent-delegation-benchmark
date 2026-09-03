import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark.public_characterization_v2 import BASELINE_TARGET, FAMILIES, PILOT_CONFIGURATIONS
from benchmark.public_characterization_v2.evaluate import evaluate
from benchmark.public_characterization_v2.generate import make_instance, materialize, workspace_digest
from benchmark.public_characterization_v2.runner import derive_scores, prohibited_files, validate_preflight
from benchmark.review_bundle import create_review_bundle


class PublicCharacterizationV2Tests(unittest.TestCase):
    def test_all_initial_variants_have_headroom_and_visible_controller_parity(self):
        for index, family in enumerate(FAMILIES):
            instance = make_instance(family, 20261001 + index)
            with tempfile.TemporaryDirectory() as temporary:
                workspace = Path(temporary) / "workspace"
                materialize(instance, workspace)
                controller = evaluate(instance, workspace)
                self.assertGreaterEqual(controller["score"], BASELINE_TARGET[0])
                self.assertLessEqual(controller["score"], BASELINE_TARGET[1])
                self.assertEqual(len(controller["check_vector"]), 8)

    def test_score_derivatives_preserve_absolute_and_conditional_metrics(self):
        self.assertEqual(derive_scores(25.0, 75.0), {"delta_score": 50.0, "normalized_improvement": 2 / 3})
        self.assertEqual(derive_scores(75.0, None), {"delta_score": None, "normalized_improvement": None})

    def test_edit_scope_ignores_generated_noise_but_rejects_immutable_files(self):
        scope = {"editable": ["app/**/*.py"], "immutable": ["tests/**"]}
        self.assertEqual(prohibited_files(["app/store.py", "__pycache__/store.pyc", ".pytest_cache/x"], scope), [])
        self.assertEqual(prohibited_files(["tests/test_contract.py"], scope), ["tests/test_contract.py"])

    def test_v2_is_fixed_to_three_pilot_configurations(self):
        self.assertEqual(PILOT_CONFIGURATIONS, (("gemini-3.7-flash-low", "low"), ("gemini-3.7-flash-medium", "medium"), ("gemini-3.8-flash-low", "low")))
        self.assertEqual(len(PILOT_CONFIGURATIONS) * len(FAMILIES), 12)

    def test_preflight_does_not_require_or_invoke_model(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            with patch("benchmark.public_characterization_v2.runner.state_root", return_value=state), patch("benchmark.public_characterization_v2.runner.validate_git_identity", return_value={"git_sha": "test"}):
                result = validate_preflight(require_reference=False)
            self.assertFalse(result["ok"])  # reference metadata is intentionally absent in this test
            self.assertEqual(result["gates"]["headroom"], True)
            self.assertEqual(result["gates"]["visible_controller_parity"], True)

    def test_v2_bundle_includes_public_design_artifacts_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"; (state / "evidence").mkdir(parents=True)
            (state / "run-summary.json").write_text(json.dumps({"evaluation_class": "public_characterization", "attempts": 0}))
            (state / "task-specifications/P1").mkdir(parents=True)
            (state / "task-specifications/P1/README.md").write_text("public requirements")
            (state / "verifier-contracts/P1").mkdir(parents=True)
            (state / "verifier-contracts/P1/contract.py").write_text("public checks")
            (state / "edit-scopes/P1").mkdir(parents=True)
            (state / "edit-scopes/P1/allowed-edit-manifest.json").write_text("{}")
            (state / "ledger.sqlite3").write_text("excluded")
            (state / "workspaces").mkdir()
            result = create_review_bundle("public-characterization-v2", state_dir=state, output=Path(temporary) / "bundle")
            bundle = Path(result["bundle"])
            self.assertTrue((bundle / "task-specifications/P1/README.md").exists())
            self.assertTrue((bundle / "verifier-contracts/P1/contract.py").exists())
            self.assertTrue((bundle / "edit-scopes/P1/allowed-edit-manifest.json").exists())
            self.assertFalse((bundle / "ledger.sqlite3").exists())
            self.assertFalse((bundle / "workspaces").exists())

    def test_workspace_hash_is_repeatable_for_same_seed(self):
        instance = make_instance("P4_compat_refactor", 20261004)
        with tempfile.TemporaryDirectory() as temporary:
            a, b = Path(temporary) / "a", Path(temporary) / "b"
            materialize(instance, a); materialize(instance, b)
            self.assertEqual(workspace_digest(a), workspace_digest(b))


if __name__ == "__main__":
    unittest.main()
