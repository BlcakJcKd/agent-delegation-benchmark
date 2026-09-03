import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
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

    def test_public_package_scripts_are_exactly_ekalavya_and_eka(self):
        import tomllib
        metadata = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
        self.assertEqual(set(metadata["project"]["scripts"]), {"eka", "ekalavya"})


if __name__ == "__main__":
    unittest.main()
