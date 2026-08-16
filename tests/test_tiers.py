import unittest

from benchmark.tiers import PILOT_RUN_LABELS, TIERS


class TierTests(unittest.TestCase):
    def test_tiers_are_explicit_and_role_separated(self):
        tier_a = TIERS["tier-a-medium"]
        tier_b = TIERS["tier-b-cheap"]
        self.assertEqual(tier_a.models["codex"], "gpt-5.6-terra")
        self.assertEqual(tier_a.models["agy"], "gemini-3.1-pro-low")
        self.assertEqual(tier_b.models["codex"], "gpt-5.6-luna")
        self.assertEqual(tier_b.models["claude"], "claude-haiku-4-5-20251001")
        self.assertEqual(tier_b.models["agy"], "gemini-3.7-flash-medium")
        self.assertEqual(tier_a.codex_reasoning_effort, "medium")
        self.assertEqual(tier_b.claude_reasoning_effort, "medium")

    def test_all_existing_runs_are_pilot_only(self):
        self.assertEqual(PILOT_RUN_LABELS, {
            "first-comparison",
            "first-valid-comparison",
            "first-valid-codex-repair",
            "first-valid-codex-terra",
        })
