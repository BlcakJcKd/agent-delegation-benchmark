import unittest

from benchmark.cross_provider_characterization_r1 import CONFIGS, FAMILIES, R1_1_SHA, RUN_ORDER, TIMEOUT_SECONDS
from benchmark.cross_provider_characterization_r1.runner import _scope_validation, _frozen_task_validation, instances
from benchmark.edit_scope import matches_edit_scope


class CrossProviderR1Tests(unittest.TestCase):
    def test_exact_frozen_source_and_budget(self):
        self.assertEqual(R1_1_SHA, "78298561c5542bec5a2b87aff34179871522e7ac")
        self.assertEqual(TIMEOUT_SECONDS, 420)
        self.assertEqual(len(RUN_ORDER), 8)
        self.assertEqual({item[0] for item in RUN_ORDER}, {0, 1})
        self.assertEqual({item[1] for item in RUN_ORDER}, set(range(4)))

    def test_exact_candidate_identities_and_no_gemini_new_cells(self):
        self.assertEqual([c["model"] for c in CONFIGS], ["deepseek-v4-flash", "MiniMax-M3"])
        self.assertTrue(all(c["reasoning"] == "high" and c["transport"] == "codex" for c in CONFIGS))

    def test_frozen_task_hashes_match_retained_r11(self):
        self.assertEqual(_frozen_task_validation(instances())["status"], "pass")

    def test_real_task_scope_validation(self):
        result = _scope_validation(instances())
        self.assertEqual(result["status"], "pass")
        for task in result["tasks"]:
            self.assertTrue(all(task["checks"].values()))

    def test_recursive_scope_semantics(self):
        self.assertTrue(matches_edit_scope("inventory/api.py", ("inventory/**/*.py",)))
        self.assertTrue(matches_edit_scope("inventory/foo/bar/api.py", ("inventory/**/*.py",)))
        self.assertFalse(matches_edit_scope("tests/test_contract.py", ("inventory/**/*.py",)))

    def test_families_are_the_frozen_four(self):
        self.assertEqual(FAMILIES, ("R1_maintenance", "R2_api_compat", "R3_scientific_pipeline", "R4_config_state"))


if __name__ == "__main__":
    unittest.main()
