"""Tests for delegation.routing (primary alias / route-type classification)
and delegation.status (zero-model-call effective routing computation)."""

from __future__ import annotations

import unittest

from delegation.config import default_config, set_enabled
from delegation.routing import normalize_primary, route_type
from delegation.status import compute_status


class NormalizePrimaryTests(unittest.TestCase):
    def test_none_and_blank_are_undeclared(self):
        self.assertIsNone(normalize_primary(None))
        self.assertIsNone(normalize_primary(""))
        self.assertIsNone(normalize_primary("   "))

    def test_known_aliases_normalize_to_a_provider_or_manual(self):
        self.assertEqual(normalize_primary("claude-code"), "claude")
        self.assertEqual(normalize_primary("Claude"), "claude")
        self.assertEqual(normalize_primary("CODEX"), "codex")
        self.assertEqual(normalize_primary("antigravity"), "gemini")
        self.assertEqual(normalize_primary("agy"), "gemini")
        self.assertEqual(normalize_primary("manual"), "manual")
        self.assertEqual(normalize_primary("human"), "manual")

    def test_unknown_alias_raises(self):
        with self.assertRaisesRegex(ValueError, "unknown --primary value"):
            normalize_primary("bogus")


class RouteTypeTests(unittest.TestCase):
    def test_terra_and_luna_are_always_native_only(self):
        for primary in (None, "codex", "claude", "gemini", "manual"):
            self.assertEqual(route_type("terra", primary), "native-only")
            self.assertEqual(route_type("luna", primary), "native-only")

    def test_wrapper_routes_are_external_for_a_different_or_undeclared_primary(self):
        self.assertEqual(route_type("flash", None), "external")
        self.assertEqual(route_type("flash", "claude"), "external")
        self.assertEqual(route_type("flash", "codex"), "external")
        self.assertEqual(route_type("haiku", "codex"), "external")
        self.assertEqual(route_type("sonnet", "gemini"), "external")

    def test_wrapper_routes_are_same_provider_for_a_matching_primary(self):
        self.assertEqual(route_type("haiku", "claude"), "same-provider")
        self.assertEqual(route_type("sonnet", "claude"), "same-provider")
        self.assertEqual(route_type("flash", "gemini"), "same-provider")

    def test_manual_primary_never_produces_same_provider(self):
        self.assertEqual(route_type("flash", "manual"), "external")
        self.assertEqual(route_type("haiku", "manual"), "external")


class ComputeStatusTests(unittest.TestCase):
    def _which_all_present(self, name):
        return f"/usr/bin/{name}"

    def _which_none_present(self, name):
        return None

    def test_zero_model_calls_only_uses_injected_which(self):
        calls = []

        def spy_which(name):
            calls.append(name)
            return f"/usr/bin/{name}"

        compute_status(default_config(), primary="claude-code", which=spy_which)
        self.assertEqual(set(calls), {"claude", "agy"})  # only wrapper executables probed

    def test_enabled_external_route_with_executable_present_is_available(self):
        results = {r.route: r for r in compute_status(default_config(), primary=None, which=self._which_all_present)}
        self.assertEqual(results["flash"].effective, "available")
        self.assertEqual(results["flash"].route_type, "external")

    def test_enabled_external_route_with_missing_executable_is_reported_clearly(self):
        results = {r.route: r for r in compute_status(default_config(), primary=None, which=self._which_none_present)}
        self.assertEqual(results["flash"].effective, "executable missing")
        self.assertIn("agy", results["flash"].effective_reason)

    def test_same_provider_route_is_native_only_regardless_of_executable(self):
        results = {r.route: r for r in compute_status(default_config(), primary="claude-code", which=self._which_all_present)}
        self.assertEqual(results["haiku"].effective, "native-only")
        self.assertEqual(results["sonnet"].effective, "native-only")
        self.assertEqual(results["flash"].effective, "available")  # gemini != claude primary

    def test_native_only_routes_report_native_only_when_enabled(self):
        results = {r.route: r for r in compute_status(default_config(), primary="claude-code", which=self._which_all_present)}
        self.assertEqual(results["terra"].effective, "native-only")
        self.assertEqual(results["luna"].effective, "native-only")

    def test_provider_disable_overrides_individual_model_enabled_preference(self):
        config = set_enabled(default_config(), "providers", "codex", False, reason="weekly quota low")
        results = {r.route: r for r in compute_status(config, primary=None, which=self._which_all_present)}
        self.assertTrue(results["terra"].configured_enabled is False)
        self.assertTrue(results["luna"].configured_enabled is False)
        self.assertEqual(results["terra"].effective, "disabled")
        self.assertEqual(results["terra"].effective_reason, "weekly quota low")

    def test_re_enabling_provider_restores_untouched_model_preferences(self):
        config = set_enabled(default_config(), "providers", "codex", False, reason="quota low")
        config = set_enabled(config, "providers", "codex", True)
        results = {r.route: r for r in compute_status(config, primary=None, which=self._which_all_present)}
        self.assertEqual(results["terra"].effective, "native-only")
        self.assertEqual(results["luna"].effective, "native-only")

    def test_model_disabled_reason_used_when_provider_enabled(self):
        config = set_enabled(default_config(), "models", "flash", False, reason="testing")
        results = {r.route: r for r in compute_status(config, primary=None, which=self._which_all_present)}
        self.assertEqual(results["flash"].effective, "disabled")
        self.assertEqual(results["flash"].effective_reason, "testing")

    def test_provider_reason_takes_precedence_over_model_reason_when_both_disabled(self):
        config = set_enabled(default_config(), "providers", "gemini", False, reason="provider-level")
        config = set_enabled(config, "models", "flash", False, reason="model-level")
        results = {r.route: r for r in compute_status(config, primary=None, which=self._which_all_present)}
        self.assertEqual(results["flash"].effective_reason, "provider-level")

    def test_route_status_is_json_serializable_via_as_dict(self):
        import json
        results = compute_status(default_config(), primary="codex", which=self._which_all_present)
        json.dumps([r.as_dict() for r in results])  # must not raise

    def test_unknown_primary_propagates_from_compute_status(self):
        with self.assertRaises(ValueError):
            compute_status(default_config(), primary="not-a-real-provider")


if __name__ == "__main__":
    unittest.main()
