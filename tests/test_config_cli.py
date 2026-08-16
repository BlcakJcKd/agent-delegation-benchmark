"""Tests for the delegate-config non-interactive subcommands.

Every test isolates XDG_CONFIG_HOME to a temp dir so nothing here can ever
read or write the real user config. No model calls anywhere in this file.
"""

from __future__ import annotations

import io
import json
import os
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from delegation.config_cli import main


class ConfigCliTests(unittest.TestCase):
    def _isolated_xdg(self, temp: str):
        return patch.dict(os.environ, {"XDG_CONFIG_HOME": str(Path(temp) / "config")}, clear=False)

    def _config_file(self, temp: str) -> Path:
        return Path(temp) / "config" / "agent-delegation" / "config.toml"

    def test_list_on_fresh_install_shows_everything_enabled(self):
        with TemporaryDirectory() as temp, self._isolated_xdg(temp):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["list"])
            self.assertEqual(code, 0)
            self.assertIn("flash", buf.getvalue())
            self.assertIn("enabled", buf.getvalue())
            self.assertFalse(self._config_file(temp).exists(), "a read-only list must not create the file")

    def test_list_json_is_the_full_schema(self):
        with TemporaryDirectory() as temp, self._isolated_xdg(temp):
            buf = io.StringIO()
            with redirect_stdout(buf):
                main(["list", "--json"])
            payload = json.loads(buf.getvalue())
            self.assertEqual(set(payload), {"providers", "models"})

    def test_disable_creates_the_config_file_atomically(self):
        with TemporaryDirectory() as temp, self._isolated_xdg(temp):
            code = main(["disable", "flash", "--reason", "weekly quota low"])
            self.assertEqual(code, 0)
            path = self._config_file(temp)
            self.assertTrue(path.is_file())
            self.assertIn("weekly quota low", path.read_text())
            leftovers = [p for p in path.parent.iterdir() if p != path]
            self.assertEqual(leftovers, [])

    def test_enable_after_disable_clears_reason_and_reports_change(self):
        with TemporaryDirectory() as temp, self._isolated_xdg(temp):
            main(["disable", "flash", "--reason", "weekly quota low"])
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main(["enable", "flash"])
            self.assertEqual(code, 0)
            self.assertIn("disabled -> enabled", buf.getvalue())
            self.assertNotIn("weekly quota low", self._config_file(temp).read_text())

    def test_disable_provider_overrides_model_enable_in_stored_config(self):
        with TemporaryDirectory() as temp, self._isolated_xdg(temp):
            main(["disable-provider", "codex", "--reason", "quota low"])
            buf = io.StringIO()
            with redirect_stdout(buf):
                main(["list", "--json"])
            config = json.loads(buf.getvalue())
            self.assertFalse(config["providers"]["codex"]["enabled"])
            self.assertTrue(config["models"]["terra"]["enabled"], "model preference must be untouched")
            self.assertTrue(config["models"]["luna"]["enabled"])

    def test_enable_provider_restores_without_touching_model_entries(self):
        with TemporaryDirectory() as temp, self._isolated_xdg(temp):
            main(["disable-provider", "codex", "--reason", "quota low"])
            main(["enable-provider", "codex"])
            buf = io.StringIO()
            with redirect_stdout(buf):
                main(["list", "--json"])
            config = json.loads(buf.getvalue())
            self.assertTrue(config["providers"]["codex"]["enabled"])
            self.assertNotIn("reason", config["providers"]["codex"])
            self.assertTrue(config["models"]["terra"]["enabled"])

    def test_unknown_route_name_is_rejected_by_argparse(self):
        with TemporaryDirectory() as temp, self._isolated_xdg(temp):
            with self.assertRaises(SystemExit):
                main(["disable", "gpt5"])

    def test_unknown_provider_name_is_rejected_by_argparse(self):
        with TemporaryDirectory() as temp, self._isolated_xdg(temp):
            with self.assertRaises(SystemExit):
                main(["disable-provider", "openai"])

    def test_idempotent_disable_reports_no_change(self):
        with TemporaryDirectory() as temp, self._isolated_xdg(temp):
            main(["disable", "flash", "--reason", "x"])
            buf = io.StringIO()
            with redirect_stdout(buf):
                main(["disable", "flash", "--reason", "x"])
            self.assertIn("no change", buf.getvalue())

    def test_disable_does_not_touch_unrelated_entries_on_disk(self):
        with TemporaryDirectory() as temp, self._isolated_xdg(temp):
            main(["disable", "flash", "--reason", "x"])
            main(["disable", "haiku", "--reason", "y"])
            buf = io.StringIO()
            with redirect_stdout(buf):
                main(["list", "--json"])
            config = json.loads(buf.getvalue())
            self.assertFalse(config["models"]["flash"]["enabled"])
            self.assertFalse(config["models"]["haiku"]["enabled"])
            self.assertTrue(config["models"]["sonnet"]["enabled"])

    def test_json_output_for_a_mutation(self):
        with TemporaryDirectory() as temp, self._isolated_xdg(temp):
            buf = io.StringIO()
            with redirect_stdout(buf):
                main(["disable", "flash", "--reason", "x", "--json"])
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["name"], "flash")
            self.assertFalse(payload["after"]["enabled"])

    def test_no_subcommand_without_a_tty_prints_usage_and_exits_nonzero(self):
        # redirect_stdout swaps in a plain StringIO, whose isatty() is False,
        # which is exactly the "not a terminal" case this exercises.
        with TemporaryDirectory() as temp, self._isolated_xdg(temp):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = main([])
            self.assertEqual(code, 2)
            self.assertIn("subcommand", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
