import tempfile
import unittest
from pathlib import Path

from benchmark.edit_scope import matches_edit_scope
from benchmark.gemini_reasoning_r1_1 import FAMILIES
from benchmark.gemini_reasoning_r1_1 import SEEDS, SUITE_NAME, SUITE_VERSION, TIMEOUT_SECONDS
from benchmark.gemini_reasoning_r1_1.generate import make_instance, materialize, task_hashes
from benchmark.gemini_reasoning_r1_1.runner import MODELS, REASONING, RUN_ORDER


class GeminiReasoningR11Tests(unittest.TestCase):
    def test_new_identity_and_fresh_seeds(self):
        self.assertEqual(SUITE_NAME, "gemini-3.8-reasoning-r1.1")
        self.assertEqual(SUITE_VERSION, "1.1")
        self.assertTrue(all(seed >= 20261004 for seed in SEEDS.values()))
        for family in FAMILIES:
            self.assertNotEqual(make_instance(family).task_id, f"gemini-3.8-reasoning-r1:{family}@20260904")

    def test_exact_models_and_balanced_order(self):
        self.assertEqual(MODELS, ("gemini-3.8-flash-low", "gemini-3.8-flash-medium", "gemini-3.8-flash-high"))
        self.assertEqual(REASONING, ("low", "medium", "high"))
        self.assertEqual(len(RUN_ORDER), 12)
        self.assertEqual({(task, model) for task, model in RUN_ORDER}, {(task, model) for task in range(4) for model in range(3)})
        self.assertEqual(TIMEOUT_SECONDS, 420)

    def test_fresh_hashes_are_matched_only_within_r11(self):
        for family in FAMILIES:
            instance = make_instance(family)
            self.assertEqual(task_hashes(instance), task_hashes(make_instance(family, SEEDS[family])))
        self.assertNotEqual(task_hashes(make_instance("R1_maintenance"))["task_spec_hash"], "d50daf3103880dbe5605a8c0943338f60d5d1430e3b473e3ff78929b81f44442")

    def test_real_task_scope_paths_use_generic_recursive_semantics(self):
        for family in FAMILIES:
            instance = make_instance(family)
            source = next(name for name in instance.files if name.endswith(".py") and not name.startswith("tests/"))
            self.assertTrue(matches_edit_scope(source, instance.editable), (family, source))
            self.assertFalse(matches_edit_scope("tests/test_contract.py", instance.editable), family)
            self.assertFalse(matches_edit_scope("unrelated/escape.py", instance.editable), family)

    def test_baseline_has_eight_checks_and_headroom(self):
        from benchmark.gemini_reasoning_r1_1.evaluate import evaluate, visible_check_vector
        for family in FAMILIES:
            instance = make_instance(family)
            with tempfile.TemporaryDirectory() as temp:
                workspace = Path(temp) / "workspace"
                materialize(instance, workspace)
                result = evaluate(instance, workspace)
                self.assertEqual(len(result["check_vector"]), 8)
                self.assertLess(result["score"], 75)
                self.assertEqual(result["check_vector"], visible_check_vector(workspace, family))


if __name__ == "__main__":
    unittest.main()
