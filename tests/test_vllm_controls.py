"""Hermetic control-plane tests for named local vLLM routes.

These tests use only example.invalid fixtures and never resolve credentials or
contact a model server.
"""

from __future__ import annotations

import io
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from delegation.config import load_config, set_enabled
from delegation.config_cli import main as config_main
from delegation.config_tui import build_rows, rows_to_config, toggle
from delegation.status import compute_status
from delegation.status_cli import build_report
from delegation.vllm import inspect_vllm_routes


REPO_ROOT = Path(__file__).resolve().parents[1]


def write_vllm(path: Path, *, route: str = "lab-qwen", model: str = "Qwen/example-model", credential: bool = True) -> None:
    path.write_text(
        f"[providers.{route}]\n"
        f'model = "{model}"\n'
        'base_url = "http://vllm.example.invalid/v1"\n'
        + ('credential_source = "env:LAB_VLLM_TOKEN"\n' if credential else '')
        + "shared_compute = true\n"
        "max_concurrency = 1\n"
        "thinking_default = false\n"
        "max_tokens = 128\n"
    )


class VLLMControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config_home = self.root / "config"
        self.config_dir = self.config_home / "agent-delegation"
        self.config_dir.mkdir(parents=True)
        self.vllm_path = self.config_dir / "vllm.toml"
        write_vllm(self.vllm_path)
        self.xdg = patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.config_home)}, clear=False)
        self.xdg.start()

    def tearDown(self) -> None:
        self.xdg.stop()
        self.temp.cleanup()

    def test_delegate_config_discovers_route_and_displays_local_model_policy_offline(self):
        output = io.StringIO()
        with patch("delegation.vllm.urllib.request.urlopen", side_effect=AssertionError("network call")), redirect_stdout(output):
            self.assertEqual(config_main(["list"]), 0)
        text = output.getvalue()
        self.assertIn("lab-qwen", text)
        self.assertIn("Qwen/example-model", text)
        self.assertIn("shared vLLM / OpenAI-compatible", text)
        self.assertIn("shared compute: yes", text)
        self.assertIn("concurrency: 1", text)
        self.assertIn("thinking default: off", text)
        self.assertNotIn("example.invalid", text)

    def test_enable_disable_route_persists_only_availability_and_preserves_vllm_definition(self):
        before = self.vllm_path.read_text()
        self.assertEqual(config_main(["disable", "lab-qwen", "--reason", "maintenance"]), 0)
        config = load_config()
        self.assertFalse(config["vllm"]["lab-qwen"]["enabled"])
        self.assertEqual(config["vllm"]["lab-qwen"]["reason"], "maintenance")
        self.assertEqual(self.vllm_path.read_text(), before)
        self.assertEqual(config_main(["enable", "lab-qwen"]), 0)
        config = load_config()
        self.assertTrue(config["vllm"]["lab-qwen"]["enabled"])
        self.assertNotIn("reason", config["vllm"]["lab-qwen"])
        self.assertEqual(self.vllm_path.read_text(), before)

    def test_migration_defaults_existing_local_route_to_enabled_without_rewriting_old_config(self):
        old_config = self.config_dir / "config.toml"
        old_config.write_text("[providers.codex]\nenabled = false\nreason = \"user choice\"\n")
        loaded = load_config()
        self.assertTrue(loaded["vllm"]["lab-qwen"]["enabled"])
        self.assertFalse(loaded["providers"]["codex"]["enabled"])
        self.assertEqual(loaded["providers"]["codex"]["reason"], "user choice")
        self.assertNotIn("[vllm", old_config.read_text())

    def test_tui_row_contains_route_details_and_toggle_round_trips(self):
        config = load_config()
        rows = build_rows(config, inspect_vllm_routes(self.vllm_path))
        row = next(row for row in rows if row.kind == "vllm")
        self.assertEqual(row.name, "lab-qwen")
        self.assertIn("model: Qwen/example-model", row.details)
        self.assertIn("concurrency: 1", row.details)
        index = next(i for i, candidate in enumerate(rows) if candidate.name == "lab-qwen")
        updated = rows_to_config(config, toggle(rows, index))
        self.assertFalse(updated["vllm"]["lab-qwen"]["enabled"])
        self.assertTrue(config["vllm"]["lab-qwen"]["enabled"])

    def test_status_available_disabled_and_all_primary_modes_are_external(self):
        route_info = inspect_vllm_routes(self.vllm_path)
        config = load_config()
        for primary in ("codex", "claude-code", "manual"):
            result = {item.route: item for item in compute_status(config, primary, which=lambda _: "/bin/example", vllm_routes=route_info)}
            self.assertEqual(result["lab-qwen"].effective, "available")
            self.assertEqual(result["lab-qwen"].route_type, "external")
            self.assertEqual(result["lab-qwen"].provider, "vllm")
            self.assertEqual(result["lab-qwen"].model, "Qwen/example-model")
            self.assertTrue(result["lab-qwen"].shared_compute)
        disabled = set_enabled(config, "vllm", "lab-qwen", False, reason="user disabled")
        item = next(item for item in compute_status(disabled, "codex", which=lambda _: "/bin/example", vllm_routes=route_info) if item.route == "lab-qwen")
        self.assertEqual(item.effective, "disabled")
        self.assertEqual(item.effective_reason, "user disabled")

    def test_status_invalid_and_missing_credential_reference_are_safe(self):
        invalid = self.root / "invalid.toml"
        invalid.write_text('[providers.lab-qwen]\nbase_url = "http://vllm.example.invalid/v1"\ncredential_source = "env:LAB_VLLM_TOKEN"\n')
        missing = self.root / "missing-credential.toml"
        write_vllm(missing, credential=False)
        invalid_item = next(iter(inspect_vllm_routes(invalid).values()))
        missing_item = next(iter(inspect_vllm_routes(missing).values()))
        self.assertEqual(invalid_item.error_kind, "invalid-configuration")
        self.assertEqual(missing_item.error_kind, "missing-credential-reference")
        config = {"providers": {}, "models": {}, "vllm": {"lab-qwen": {"enabled": True}}}
        statuses = compute_status(config, vllm_routes={"lab-qwen": missing_item})
        self.assertEqual(statuses[-1].effective, "missing credential reference")
        report = build_report("manual", config=config, vllm_routes={"lab-qwen": invalid_item}, which=lambda _: "/bin/example")
        route = report["routes"][-1]
        self.assertEqual(route["effective"], "invalid configuration")
        self.assertNotIn("LAB_VLLM_TOKEN", str(route))
        self.assertNotIn("example.invalid", str(route))

    def test_status_and_config_render_do_not_call_urlopen(self):
        route_info = inspect_vllm_routes(self.vllm_path)
        with patch("delegation.vllm.urllib.request.urlopen", side_effect=AssertionError("network call")) as urlopen:
            build_report("codex", config=load_config(), vllm_routes=route_info, which=lambda _: "/bin/example")
            config_main(["list"])
        urlopen.assert_not_called()


class PublicBoundaryTests(unittest.TestCase):
    def test_public_vllm_fixture_and_skill_use_generic_identity(self):
        fixture = (REPO_ROOT / "provider_templates" / "vllm.toml.example").read_text()
        skill = (REPO_ROOT / "skills" / "delegation" / "SKILL.md").read_text()
        for text in (fixture, skill):
            self.assertNotIn("Qwen/Qwen3.5-9B", text)
            self.assertNotIn("qwen35-9b-craig", text)
            self.assertNotIn("Tailscale", text)
        self.assertIn("example.invalid", fixture)
        self.assertIn("vLLM", skill)
        self.assertIn("ask-vllm <named-route>", skill)
        self.assertIn("speculative fan-out", skill)


if __name__ == "__main__":
    unittest.main()
