"""Tests for the self-provider routing guard in delegation.core.

Distinct from the recursion-depth guard (see test_delegation.py
DelegationRecursionGuardTests): this guard stops a declared primary from
externally calling its own provider. Every case here uses a mocked ``run``;
no real delegate CLI is invoked.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from delegation.core import run_consultation

TASK = "self-provider guard probe; do not modify anything"


class SelfProviderGuardTests(unittest.TestCase):
    def _scope(self, root: Path) -> Path:
        workspace = root / "scope"
        workspace.mkdir()
        (workspace / ".delegation-scope.json").write_text(json.dumps({"mode": "read-only"}))
        return workspace

    def _fake_run(self, calls):
        def run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, stdout="ok", stderr="")
        return run

    def test_claude_primary_calling_haiku_is_rejected_without_launching_a_process(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self._scope(root)
            calls = []
            with self.assertRaisesRegex(ValueError, "same-provider external delegation disabled"):
                run_consultation(
                    "haiku", workspace, TASK, log_root=root / "logs",
                    run=self._fake_run(calls), primary="claude-code",
                )
            self.assertEqual(calls, [])

    def test_claude_primary_calling_sonnet_is_rejected(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self._scope(root)
            calls = []
            with self.assertRaises(ValueError):
                run_consultation(
                    "sonnet", workspace, TASK, log_root=root / "logs",
                    run=self._fake_run(calls), primary="claude",
                )
            self.assertEqual(calls, [])

    def test_claude_primary_calling_flash_is_allowed(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self._scope(root)
            calls = []
            code, record_dir = run_consultation(
                "flash", workspace, TASK, log_root=root / "logs",
                run=self._fake_run(calls), primary="claude-code",
            )
            self.assertEqual(code, 0)
            self.assertEqual(len(calls), 1)
            record = json.loads((record_dir / "execution.json").read_text())
            self.assertEqual(record["declared_primary"], "claude")

    def test_gemini_primary_calling_flash_is_rejected(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self._scope(root)
            calls = []
            with self.assertRaisesRegex(ValueError, "same-provider external delegation disabled"):
                run_consultation(
                    "flash", workspace, TASK, log_root=root / "logs",
                    run=self._fake_run(calls), primary="gemini",
                )
            self.assertEqual(calls, [])

    def test_gemini_primary_calling_claude_routes_is_allowed(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self._scope(root)
            calls = []
            for delegate in ("haiku", "sonnet"):
                code, _ = run_consultation(
                    delegate, workspace, TASK, log_root=root / "logs",
                    run=self._fake_run(calls), primary="antigravity",
                )
                self.assertEqual(code, 0)
            self.assertEqual(len(calls), 2)

    def test_codex_primary_may_use_any_external_route_codex_has_no_wrapper(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self._scope(root)
            calls = []
            for delegate in ("flash", "haiku", "sonnet"):
                code, _ = run_consultation(
                    delegate, workspace, TASK, log_root=root / "logs",
                    run=self._fake_run(calls), primary="codex",
                )
                self.assertEqual(code, 0)
            self.assertEqual(len(calls), 3)

    def test_manual_primary_may_use_any_configured_external_route(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self._scope(root)
            calls = []
            for delegate in ("flash", "haiku", "sonnet"):
                code, _ = run_consultation(
                    delegate, workspace, TASK, log_root=root / "logs",
                    run=self._fake_run(calls), primary="manual",
                )
                self.assertEqual(code, 0)
            self.assertEqual(len(calls), 3)

    def test_undeclared_primary_does_not_enforce_the_guard(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self._scope(root)
            calls = []
            code, record_dir = run_consultation(
                "haiku", workspace, TASK, log_root=root / "logs", run=self._fake_run(calls),
            )
            self.assertEqual(code, 0)
            record = json.loads((record_dir / "execution.json").read_text())
            self.assertEqual(record["declared_primary"], "not-declared")

    def test_unknown_primary_value_is_rejected_without_launching_a_process(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self._scope(root)
            calls = []
            with self.assertRaisesRegex(ValueError, "unknown --primary value"):
                run_consultation(
                    "flash", workspace, TASK, log_root=root / "logs",
                    run=self._fake_run(calls), primary="not-a-real-thing",
                )
            self.assertEqual(calls, [])

    def test_self_provider_guard_is_independent_of_recursion_guard(self):
        # A same-provider primary rejection must not be confused with, or
        # bypass, the recursion-depth guard's own independent check.
        import os
        from unittest.mock import patch
        from delegation.core import DELEGATION_DEPTH_ENV

        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self._scope(root)
            calls = []
            with patch.dict(os.environ, {DELEGATION_DEPTH_ENV: "1"}, clear=False):
                with self.assertRaisesRegex(ValueError, "recursive delegation rejected"):
                    run_consultation(
                        "flash", workspace, TASK, log_root=root / "logs",
                        run=self._fake_run(calls), primary="claude-code",
                    )
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
