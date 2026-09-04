import tempfile
import unittest
from pathlib import Path

from benchmark.gemini_reasoning_r1 import FAMILIES, SEEDS, SUITE_NAME, TIMEOUT_SECONDS
from benchmark.gemini_reasoning_r1.evaluate import evaluate, visible_check_vector
from benchmark.gemini_reasoning_r1.generate import make_instance, materialize, task_hashes


class GeminiReasoningR1Tests(unittest.TestCase):
    def test_portfolio_is_four_fresh_deterministic_tasks(self):
        self.assertEqual(len(FAMILIES), 4)
        self.assertEqual(len(set(SEEDS.values())), 4)
        for family in FAMILIES:
            first = make_instance(family)
            second = make_instance(family, SEEDS[family])
            self.assertEqual(first.files, second.files)
            self.assertEqual(first.prompt, second.prompt)
            self.assertEqual(first.task_id, f"{SUITE_NAME}:{family}@{SEEDS[family]}")

    def test_baselines_are_headroom_below_seventy_five_and_visible_parity_holds(self):
        for family in FAMILIES:
            instance = make_instance(family)
            with tempfile.TemporaryDirectory() as temp:
                workspace = Path(temp) / "workspace"
                materialize(instance, workspace)
                controller = evaluate(instance, workspace)
                self.assertEqual(len(controller["check_vector"]), 8)
                self.assertLess(controller["score"], 75)
                self.assertEqual(controller["check_vector"], visible_check_vector(workspace, family))

    def test_hashes_repeat_for_same_seed_and_budget_is_fixed(self):
        for family in FAMILIES:
            self.assertEqual(task_hashes(make_instance(family)), task_hashes(make_instance(family)))
        self.assertEqual(TIMEOUT_SECONDS, 420)

    def test_task_has_no_answer_bearing_reference_source(self):
        for family in FAMILIES:
            instance = make_instance(family)
            source = "\n".join(instance.files.values()).lower()
            self.assertNotIn("gold patch", source)
            self.assertNotIn("reference implementation", source)
            self.assertNotIn("apply_patch", source)


if __name__ == "__main__":
    unittest.main()
