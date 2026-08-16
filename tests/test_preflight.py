import unittest

from benchmark.preflight import parse_models


class ModelSelectionTests(unittest.TestCase):
    def test_missing_models_are_a_preflight_blocker(self):
        models, errors = parse_models(None, ["codex", "claude", "agy"])
        self.assertEqual(models, {})
        self.assertEqual(errors, ["model selection required for: codex, claude, agy"])

    def test_explicit_models_are_parsed_without_shell_splitting(self):
        models, errors = parse_models("codex=gpt-x,claude=sonnet,agy=gemini-3.7-flash-high", ["codex", "claude", "agy"])
        self.assertEqual(errors, [])
        self.assertEqual(models["agy"], "gemini-3.7-flash-high")
