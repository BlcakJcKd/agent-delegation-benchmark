import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from ekalavya.cli import main


class EkalavyaCliTests(unittest.TestCase):
    def _xdg(self, root: Path):
        return patch.dict(os.environ, {"XDG_CONFIG_HOME": str(root / "config"), "XDG_STATE_HOME": str(root / "state")}, clear=False)

    def _files(self, root: Path):
        config = root / "config" / "ekalavya"
        config.mkdir(parents=True)
        identity = {"provider": "claude", "family": "haiku", "provider_model_id": "claude-haiku", "display_name": "haiku", "capabilities": {"reasoning_values": ["medium"]}}
        identity["identity_key"] = "haiku-key"
        identity["lifecycle"] = "current"
        (config / "catalogue.json").write_text(json.dumps([identity]))
        (config / "profiles.json").write_text(json.dumps([{"name": "haiku", "default_identity_key": "haiku-key", "permitted_candidates": ["haiku-key"], "reasoning_policy": "fixed", "default_reasoning": "medium"}]))

    def test_status_accepts_primary_and_is_network_free(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self._files(root)
            with self._xdg(root), patch("ekalavya.cli.build_report", return_value={"routes": [], "live_vllm": {}}):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["status", "--primary", "codex", "--json"]), 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["primary"], "codex")
            self.assertIn("routing", payload)

    def test_config_mutation_is_explicit_and_json(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self._files(root)
            with self._xdg(root):
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["config", "disable-provider", "claude", "--reason", "maintenance", "--json"]), 0)
                payload = json.loads(output.getvalue())
                self.assertFalse(payload["availability"]["providers"]["claude"]["enabled"])

    def test_config_no_action_uses_tui_only_for_a_tty(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self._files(root)
            with self._xdg(root), patch("ekalavya.cli.sys.stdin.isatty", return_value=True), \
                 patch("ekalavya.cli.sys.stdout.isatty", return_value=True), \
                 patch("delegation.config_tui.run_interactive_config", return_value=0) as tui:
                self.assertEqual(main(["config"]), 0)
            tui.assert_called_once_with()

    def test_config_json_bypasses_tui_and_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self._files(root)
            with self._xdg(root), patch("ekalavya.cli.sys.stdin.isatty", return_value=True), \
                 patch("ekalavya.cli.sys.stdout.isatty", return_value=True), \
                 patch("delegation.config_tui.run_interactive_config") as tui:
                output = io.StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["config", "--json"]), 0)
                json.loads(output.getvalue())
            tui.assert_not_called()

    def test_unknown_targets_are_rejected_without_persisting_new_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); self._files(root)
            with self._xdg(root):
                for argv, text in (
                    (["config", "disable-provider", "minimx"], "unknown provider"),
                    (["config", "disable-model", "deepseek-v4-flash"], "unknown model"),
                    (["config", "disable", "route-that-does-not-exist"], "unknown model or vLLM route"),
                ):
                    error = io.StringIO()
                    with redirect_stderr(error):
                        self.assertEqual(main(argv), 2)
                    self.assertIn(text, error.getvalue())
                self.assertFalse((root / "config" / "ekalavya" / "config.toml").exists())

    def test_public_package_scripts_are_exactly_ekalavya_and_eka(self):
        import tomllib
        metadata = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
        self.assertEqual(set(metadata["project"]["scripts"]), {"eka", "ekalavya"})


if __name__ == "__main__":
    unittest.main()
