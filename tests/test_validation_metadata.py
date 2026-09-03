import unittest

from benchmark.validation_metadata import propagate_reference_status, validation_consistency


class ValidationMetadataTests(unittest.TestCase):
    def test_pending_is_not_failed(self):
        tasks = [{"family": "P1", "baseline_check_vector": [True] * 8}]
        self.assertIsNone(propagate_reference_status(tasks, None, suite="s", version="1", seed=1, suite_git_sha="x", check_count=8))
        self.assertIsNone(tasks[0]["reference_validation_passed"])

    def test_passed_global_requires_passed_every_task(self):
        tasks = [{"family": "P1", "baseline_check_vector": [True] * 8}]
        ref = {"passed": True, "suite": "s", "version": "1", "seed": 1, "suite_git_sha": "x", "tasks": [{"family": "P1", "score": 100.0, "check_vector": [True] * 8, "visible_check_vector": [True] * 8}]}
        self.assertTrue(propagate_reference_status(tasks, ref, suite="s", version="1", seed=1, suite_git_sha="x", check_count=8))
        result = {"tasks": tasks, "reference_validation": ref, "gates": {"reference_validation": True}}
        self.assertTrue(validation_consistency(result, reference_required=True, check_count=8)["ok"])

    def test_global_pass_with_task_false_is_rejected(self):
        result = {"tasks": [{"reference_validation_passed": False, "baseline_check_vector": [True] * 8}], "reference_validation": {"passed": True}, "gates": {"reference_validation": True}}
        self.assertFalse(validation_consistency(result, reference_required=True, check_count=8)["ok"])
