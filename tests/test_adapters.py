import unittest
from pathlib import Path

from benchmark.adapters import AntigravityAdapter, ClaudeAdapter, CodexAdapter, CLAUDE_TASK_ALLOWED_TOOLS
from benchmark.preflight import _adapter_command_problems


PROMPT = 'First line with spaces\nThen "quoted" text and $literal.'
WORKSPACE = Path("/tmp/benchmark workspace")
RESULT = Path("/tmp/benchmark result")


class AdapterArgvTests(unittest.TestCase):
    def test_codex_uses_directly_supported_exec_flags(self):
        command = CodexAdapter(model="chosen-codex", reasoning_effort="high").command(WORKSPACE, PROMPT, RESULT)
        self.assertEqual(command[-1], PROMPT)
        self.assertNotIn("--approve-for-me", command)
        self.assertNotIn("--ask-for-approval", command)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
        self.assertNotIn("danger-full-access", command)
        self.assertEqual(command[command.index("--sandbox") + 1], "workspace-write")
        self.assertEqual(command[command.index("--model") + 1], "chosen-codex")
        self.assertEqual(command[command.index("--config") + 1], 'model_reasoning_effort="high"')
        self.assertEqual(command[command.index("--cd") + 1], str(WORKSPACE))
        self.assertIn("--json", command)
        self.assertEqual(command[command.index("--output-last-message") + 1], str(RESULT / "last_message.txt"))
        self.assertEqual(_adapter_command_problems(CodexAdapter(model="chosen-codex", reasoning_effort="high")), [])

    def _assert_claude_task_allowlist(self, task_id, expected):
        command = ClaudeAdapter(model="chosen-claude", reasoning_effort="medium").command(
            WORKSPACE, PROMPT, RESULT, task_id=task_id,
        )
        self.assertEqual(command[-1], PROMPT)
        self.assertEqual(command[-2], "-p")
        self.assertEqual(command[command.index("--permission-mode") + 1], "auto")
        self.assertNotIn("bypassPermissions", command)
        self.assertNotIn("--dangerously-skip-permissions", command)
        self.assertNotIn("Bash", command)
        self.assertEqual(command[command.index("--model") + 1], "chosen-claude")
        self.assertEqual(command[command.index("--effort") + 1], "medium")
        self.assertEqual(command[command.index("--allowedTools") + 1], ",".join(expected))
        self.assertIn("Read", expected)
        self.assertIn("Write", expected)
        self.assertIn("Edit", expected)
        self.assertIn("Bash(python *)", expected)
        self.assertIn("Bash(python3 *)", expected)
        self.assertNotIn("Bash(*)", expected)
        self.assertNotIn("Bash(git *)", expected)
        self.assertNotIn("Bash(rm *)", expected)
        self.assertEqual(
            _adapter_command_problems(ClaudeAdapter(model="chosen-claude", reasoning_effort="medium"), task_id), [],
        )

    def test_claude_research_allowlist_is_preapproved_and_prompt_is_atomic(self):
        self._assert_claude_task_allowlist("research_python", CLAUDE_TASK_ALLOWED_TOOLS["research_python"])

    def test_claude_diagnostic_plot_allowlist_is_preapproved(self):
        self._assert_claude_task_allowlist("diagnostic_plot", CLAUDE_TASK_ALLOWED_TOOLS["diagnostic_plot"])

    def test_claude_debug_allowlist_includes_pytest_only_for_debugging(self):
        expected = CLAUDE_TASK_ALLOWED_TOOLS["debug_package"]
        self._assert_claude_task_allowlist("debug_package", expected)
        self.assertIn("Bash(pytest *)", expected)

    def test_claude_patterns_cover_common_python_commands_without_unrestricted_bash(self):
        research = CLAUDE_TASK_ALLOWED_TOOLS["research_python"]
        debug = CLAUDE_TASK_ALLOWED_TOOLS["debug_package"]
        self.assertIn("Bash(python *)", research)   # python analysis.py; python -m py_compile ...
        self.assertIn("Bash(python3 *)", research)  # python3 analysis.py; python3 -m py_compile ...
        self.assertIn("Bash(python *)", debug)      # python -m pytest
        self.assertIn("Bash(python3 *)", debug)     # python3 -m pytest
        self.assertIn("Bash(pytest *)", debug)
        self.assertNotIn("Bash(*)", research + debug)

    def test_agy_places_every_option_before_print_and_keeps_prompt_atomic(self):
        command = AntigravityAdapter(model="gemini-3.7-flash-high").command(WORKSPACE, PROMPT, RESULT)
        print_index = command.index("-p")
        self.assertEqual(print_index, len(command) - 2)
        self.assertEqual(command[-1], PROMPT)
        self.assertLess(command.index("--output-format"), print_index)
        self.assertLess(command.index("--mode"), print_index)
        self.assertLess(command.index("--sandbox"), print_index)
        self.assertLess(command.index("--model"), print_index)
        self.assertNotIn("--dangerously-skip-permissions", command)
        self.assertEqual(_adapter_command_problems(AntigravityAdapter(model="gemini-3.7-flash-high")), [])
