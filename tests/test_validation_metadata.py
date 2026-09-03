import unittest

from benchmark.validation_metadata import propagate_reference_status, validation_consistency


class ValidationMetadataTests(unittest.TestCase):
    def test_pending_reference_status_is_not_failure(self):
        tasks = [{"family": "P1", "baseline_check_vector": [False] * 8}]
        self.assertIsNone(propagate_reference_status(tasks, None, suite="s", version="1", seed=1, suite_git_sha="sha", check_count=8))
        self.assertIsNone(tasks[0]["reference_validation_passed"])

    def test_passed_reference_propagates_consistently(self):
        tasks = [{"family": "P1", "baseline_check_vector": [False] * 8}]
        reference = {"passed": True, "suite": "s", "version": "1", "seed": 1, "suite_git_sha": "sha", "tasks": [{"family": "P1", "score": 100.0, "check_vector": [True] * 8, "visible_check_vector": [True] * 8}]}
        self.assertTrue(propagate_reference_status(tasks, reference, suite="s", version="1", seed=1, suite_git_sha="sha", check_count=8))
        result = {"tasks": tasks, "reference_validation": reference, "gates": {"reference_validation": True}}
        self.assertEqual(validation_consistency(result, reference_required=True, check_count=8), {"ok": True, "reason": "consistent"})

    def test_global_pass_cannot_disagree_with_task_status(self):
        result = {"tasks": [{"reference_validation_passed": False, "baseline_check_vector": [True] * 8}], "reference_validation": {"passed": True}, "gates": {"reference_validation": True}}
        self.assertFalse(validation_consistency(result, reference_required=True, check_count=8)["ok"])
