"""Integration tests for bin/ask-* that exercise the real wrapper scripts.

These invoke the actual bash entry points as a subprocess to catch failures
the pure-Python unit tests cannot see (module resolution, cwd independence,
end-to-end recursion rejection). No model/delegate CLI is ever reached: every
case here is rejected by argument or scope validation before a delegate
would be launched.
"""

from __future__ import annotations

import json
import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
ASK_FLASH = REPO_ROOT / "bin" / "ask-flash"


class WrapperScriptTests(unittest.TestCase):
    def _scope(self, root: Path) -> Path:
        workspace = root / "scope"
        workspace.mkdir()
        (workspace / ".delegation-scope.json").write_text(json.dumps({"mode": "read-only"}))
        return workspace

    def _run_from(self, cwd: Path, *extra_args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        full_env = dict(os.environ)
        if env:
            full_env.update(env)
        return subprocess.run(
            [str(ASK_FLASH), *extra_args],
            cwd=cwd, text=True, capture_output=True, timeout=15, env=full_env,
        )

    def test_wrapper_resolves_delegation_module_from_an_arbitrary_working_directory(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            unscoped = root / "unscoped"
            unscoped.mkdir()
            result = self._run_from(root, "--workspace", str(unscoped), "--prompt", "x", "--timeout", "1")
            self.assertNotIn("ModuleNotFoundError", result.stdout + result.stderr)
            self.assertNotIn("No module named", result.stdout + result.stderr)
            self.assertIn("delegation error", result.stdout)
            self.assertEqual(result.returncode, 2)

    def test_wrapper_rejects_recursive_invocation_end_to_end_without_launching_a_model(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self._scope(root)
            result = self._run_from(
                root, "--workspace", str(workspace), "--prompt", "x", "--timeout", "1",
                env={"AGENT_DELEGATION_DEPTH": "1"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("recursive delegation rejected", result.stdout)

    def test_wrapper_rejects_malformed_depth_marker_end_to_end(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self._scope(root)
            result = self._run_from(
                root, "--workspace", str(workspace), "--prompt", "x", "--timeout", "1",
                env={"AGENT_DELEGATION_DEPTH": "not-a-number"},
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("malformed", result.stdout)


if __name__ == "__main__":
    unittest.main()
