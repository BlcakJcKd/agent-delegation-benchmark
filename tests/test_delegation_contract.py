"""Regression coverage for the external consultation result contract.

All subprocess/model boundaries are mocked or bypassed. These tests protect
the distinction between the delegate's textual result, wrapper diagnostics,
and audit metadata.
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from delegation.cli import main
from delegation.core import run_consultation


REPO_ROOT = Path(__file__).resolve().parents[1]


class AskCliResultContractTests(unittest.TestCase):
    def _record(self, root: Path, result: str, diagnostics: str = "") -> Path:
        record = root / "delegate-run"
        record.mkdir()
        (record / "stdout.txt").write_text(result)
        (record / "stderr.txt").write_text(diagnostics)
        return record

    def _invoke(self, record: Path, code: int):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with patch("delegation.cli.run_consultation", return_value=(code, record)), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            returned = main(["flash", "--workspace", str(record), "--prompt", "task"])
        return returned, stdout.getvalue(), stderr.getvalue()

    def test_success_returns_delegate_text_on_stdout_and_metadata_on_stderr(self):
        with TemporaryDirectory() as temp:
            record = self._record(Path(temp), "findings: inspect src/example.py:12\n", "provider warning\n")
            returned, stdout, stderr = self._invoke(record, 0)

        self.assertEqual(returned, 0)
        self.assertEqual(stdout, "findings: inspect src/example.py:12\n")
        self.assertIn("provider warning", stderr)
        self.assertIn("Evidence: ", stderr)
        self.assertNotIn("Evidence: ", stdout)

    def test_blank_success_is_model_response_failure(self):
        with TemporaryDirectory() as temp:
            record = self._record(Path(temp), "  \n")
            returned, stdout, stderr = self._invoke(record, 0)

        self.assertEqual(returned, 3)
        self.assertEqual(stdout, "  \n")
        self.assertIn("model/response failure", stderr)

    def test_nonzero_delegate_exit_preserves_text_but_remains_nonzero(self):
        with TemporaryDirectory() as temp:
            record = self._record(Path(temp), "provider error text\n", "authentication failed\n")
            returned, stdout, stderr = self._invoke(record, 9)

        self.assertEqual(returned, 9)
        self.assertEqual(stdout, "provider error text\n")
        self.assertIn("authentication failed", stderr)


class AuditResponseStatusTests(unittest.TestCase):
    def _scope(self, root: Path) -> Path:
        workspace = root / "scope"
        workspace.mkdir()
        (workspace / ".delegation-scope.json").write_text(json.dumps({"mode": "read-only"}))
        return workspace

    def test_audit_marks_textual_response_without_parsing_or_requiring_a_file(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            workspace = self._scope(root)

            def fake_run(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 0, stdout="nothing material to add", stderr="")

            code, record = run_consultation("flash", workspace, "task", log_root=root / "logs", run=fake_run)
            metadata = json.loads((record / "execution.json").read_text())
            self.assertEqual(code, 0)
            self.assertEqual(metadata["response_status"], "text-returned")
            self.assertEqual((record / "stdout.txt").read_text(), "nothing material to add")


class CanonicalGuidanceTests(unittest.TestCase):
    def test_skill_contains_invocation_consumption_and_diagnosis_contract(self):
        skill = (REPO_ROOT / "skills/delegation/SKILL.md").read_text()
        for required in (
            "delegate-status --primary codex",
            "ask-flash",
            "ask-terra",
            "ask-luna",
            "ask-deepseek-flash",
            "ask-deepseek-pro",
            "ask-minimax-m3",
            "ask-vllm <named-route>",
            "textual consultation returned on stdout",
            "Do not wait for or search for a review file",
            "retry at most once",
            "default `ask-*` timeout is 300 seconds",
            "externally terminated/incomplete infrastructure run",
            "exit code `124`",
            "availability/config",
            "model/response",
            "no usable textual review records",
            "SAME-PROVIDER WORK USES NATIVE AGENTS",
            "Codex/OpenAI primary",
            "Claude Code/Anthropic primary",
            "Optional machine-local coding-agent harnesses",
        ):
            self.assertIn(required, skill)

    def test_policy_contains_copyable_prompt_author_block(self):
        policy = (REPO_ROOT / "docs/DELEGATION_POLICY.md").read_text()
        self.assertIn("## Prompt-author block", policy)
        self.assertIn("Do not interpret absence of a generated file", policy)
        self.assertIn("Same-provider work uses native agents", policy)
        self.assertIn("Codex -> native Codex agents for Terra/Luna", policy)
        self.assertIn("Claude -> native Claude subagents for Sonnet/Haiku", policy)
        self.assertIn("Genuine timeout = exit 124 + timed_out:true", policy)


if __name__ == "__main__":
    unittest.main()
