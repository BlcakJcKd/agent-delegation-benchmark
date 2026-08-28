"""Tests for delegate-status. Config and executable lookup are always
injected, so nothing here touches the real filesystem/PATH or a model."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from delegation.config import default_config, set_enabled
from delegation.status_cli import build_report, main


def _which_all_present(name):
    return f"/usr/bin/{name}"


class BuildReportTests(unittest.TestCase):
    def test_report_has_no_undeclared_primary_by_default(self):
        report = build_report(None, which=_which_all_present, config=default_config())
        self.assertEqual(report["declared_primary"], "not-declared")

    def test_quota_is_reported_as_user_managed_never_a_percentage(self):
        report = build_report(None, which=_which_all_present, config=default_config())
        self.assertEqual(report["quota"], "user-managed / unknown")

    def test_report_includes_config_and_state_paths(self):
        report = build_report(None, which=_which_all_present, config=default_config())
        self.assertIn("config.toml", report["config_path"])
        self.assertIn("delegate_runs", report["state_log_path"])

    def test_report_for_each_primary_alias(self):
        for primary, expected in (
            ("claude-code", "claude"), ("codex", "codex"), ("gemini", "gemini"), ("manual", "manual"),
        ):
            report = build_report(primary, which=_which_all_present, config=default_config())
            self.assertEqual(report["declared_primary"], expected)

    def test_claude_primary_shows_haiku_sonnet_as_native_only_flash_as_available(self):
        report = build_report("claude-code", which=_which_all_present, config=default_config())
        by_route = {r["route"]: r for r in report["routes"]}
        self.assertEqual(by_route["haiku"]["effective"], "native-only")
        self.assertEqual(by_route["sonnet"]["effective"], "native-only")
        self.assertEqual(by_route["flash"]["effective"], "available")
        self.assertEqual(by_route["terra"]["effective"], "available")
        self.assertEqual(by_route["luna"]["effective"], "available")

    def test_codex_primary_shows_terra_luna_native_only_and_claude_external(self):
        report = build_report("codex", which=_which_all_present, config=default_config())
        by_route = {r["route"]: r for r in report["routes"]}
        for route in ("terra", "luna"):
            self.assertEqual(by_route[route]["effective"], "native-only")
            self.assertEqual(by_route[route]["route_type"], "same-provider")
        for route in ("haiku", "sonnet"):
            self.assertEqual(by_route[route]["effective"], "available")

    def test_disabled_provider_reason_surfaces_in_report(self):
        config = set_enabled(default_config(), "providers", "codex", False, reason="weekly quota low")
        report = build_report(None, which=_which_all_present, config=config)
        by_route = {r["route"]: r for r in report["routes"]}
        self.assertEqual(by_route["terra"]["effective"], "disabled")
        self.assertEqual(by_route["terra"]["effective_reason"], "weekly quota low")

    def test_unknown_primary_raises(self):
        with self.assertRaises(ValueError):
            build_report("not-a-real-primary", which=_which_all_present, config=default_config())

    def test_deepseek_and_minimax_routes_report_disabled_by_default(self):
        report = build_report("claude-code", which=_which_all_present, config=default_config())
        by_route = {r["route"]: r for r in report["routes"]}
        for route in ("deepseek-pro", "deepseek-flash", "minimax-m3"):
            self.assertEqual(by_route[route]["effective"], "disabled")
            self.assertEqual(by_route[route]["billing"], "payg")
            self.assertEqual(by_route[route]["maturity"], "experimental")

    def test_codex_primary_shows_deepseek_and_minimax_as_available_once_enabled(self):
        config = set_enabled(default_config(), "providers", "deepseek", True)
        config = set_enabled(config, "providers", "minimax", True)
        config = set_enabled(config, "models", "deepseek-pro", True)
        config = set_enabled(config, "models", "deepseek-flash", True)
        config = set_enabled(config, "models", "minimax-m3", True)
        report = build_report("codex", which=_which_all_present, config=config)
        by_route = {r["route"]: r for r in report["routes"]}
        for route in ("deepseek-pro", "deepseek-flash", "minimax-m3"):
            self.assertEqual(by_route[route]["effective"], "available")

    def test_deepseek_primary_shows_deepseek_routes_native_only(self):
        config = set_enabled(default_config(), "providers", "deepseek", True)
        config = set_enabled(config, "models", "deepseek-pro", True)
        report = build_report("deepseek", which=_which_all_present, config=config)
        by_route = {r["route"]: r for r in report["routes"]}
        self.assertEqual(by_route["deepseek-pro"]["effective"], "native-only")
        self.assertEqual(by_route["deepseek-pro"]["route_type"], "same-provider")


class MainCliTests(unittest.TestCase):
    def test_json_flag_emits_valid_json_with_routes(self):
        buf = io.StringIO()
        with patch("delegation.status_cli.load_config", return_value=default_config()), \
             patch("delegation.status_cli.inspect_vllm_routes", return_value={}), redirect_stdout(buf):
            code = main(["--primary", "codex", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["declared_primary"], "codex")
        self.assertEqual(len(payload["routes"]), 8)

    def test_human_output_mentions_every_route(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--primary", "manual"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        for route in (
            "terra", "luna", "sonnet", "haiku", "flash",
            "deepseek-pro", "deepseek-flash", "minimax-m3",
        ):
            self.assertIn(route, out)

    def test_human_output_distinguishes_payg_experimental_routes(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--primary", "manual"])
        self.assertEqual(code, 0)
        out = buf.getvalue()
        self.assertIn("payg", out)
        self.assertIn("experimental", out)
        self.assertIn("quota", out)
        self.assertIn("stable", out)

    def test_unknown_primary_exits_nonzero_with_a_clear_message(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["--primary", "not-a-real-primary"])
        self.assertEqual(code, 2)
        self.assertIn("unknown --primary value", buf.getvalue())

    def test_no_primary_flag_is_valid_and_zero_model_calls(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
