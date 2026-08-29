import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from benchmark.adapters import CommandAgentAdapter
from benchmark.command_agents import CommandAgentConfigurationError, load_command_agents
from benchmark.runner import execute
from benchmark.runner import main as runner_main
from benchmark.tasks import repository_root


def _copy_frozen_material(destination: Path) -> None:
    source = repository_root()
    shutil.copytree(source / "fixtures", destination / "fixtures")
    shutil.copytree(source / "tasks", destination / "tasks")
    shutil.copy2(source / "fixtures.lock.json", destination / "fixtures.lock.json")
    manifest_source = source / "private_admin/manifests/repository_review.json"
    if not manifest_source.exists():
        raise unittest.SkipTest("administrator-only manifest is absent")
    (destination / "private_admin/manifests").mkdir(parents=True)
    shutil.copy2(manifest_source, destination / "private_admin/manifests/repository_review.json")


class CommandAgentConfigTests(unittest.TestCase):
    def test_loads_argv_mapping_without_shell_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "benchmark.toml"
            path.write_text(
                '[command_agents.local-coding]\n'
                'command = ["coding-agent"]\n'
                'args = ["--non-interactive", "--mode", "write"]\n'
            )
            agents = load_command_agents(path)
        adapter = agents["local-coding"]
        self.assertEqual(adapter.command_argv, ("coding-agent",))
        self.assertEqual(adapter.fixed_args, ("--non-interactive", "--mode", "write"))

    def test_rejects_string_commands_and_unknown_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "benchmark.toml"
            path.write_text('[command_agents.bad]\ncommand = "coding-agent"\n')
            with self.assertRaises(CommandAgentConfigurationError):
                load_command_agents(path)
            path.write_text(
                '[command_agents.bad]\ncommand = ["coding-agent"]\nsecret = "no"\n'
            )
            with self.assertRaises(CommandAgentConfigurationError):
                load_command_agents(path)

    def test_runner_preflight_discovers_a_configured_command_agent_without_launching_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "benchmark.toml"
            path.write_text('[command_agents.local-coding]\ncommand = ["python3"]\n')
            self.assertEqual(
                runner_main([
                    "preflight", "--agents", "local-coding", "--tasks", "research_python",
                    "--command-agent-config", str(path),
                ]),
                0,
            )


class CommandAgentRunnerTests(unittest.TestCase):
    def _adapter(self, script: str) -> CommandAgentAdapter:
        return CommandAgentAdapter(
            name="fake-command",
            command_argv=(sys.executable,),
            fixed_args=("-c", script),
        )

    def test_successful_command_agent_edits_workspace_and_preserves_prompt_cwd_output(self):
        script = (
            "import json, os, sys; "
            "answer={'n':12,'mean_response':15.25,'control_mean':12.0,'treatment_mean':18.5,'difference':6.5}; "
            "open('answer.json','w').write(json.dumps(answer)); "
            "print(json.dumps({'cwd':os.getcwd(),'prompt':sys.argv[-1]})); "
            "print('agent stderr', file=sys.stderr)"
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _copy_frozen_material(root)
            import benchmark.runner as runner
            old = runner.ADAPTERS.get("fake-command")
            runner.ADAPTERS["fake-command"] = self._adapter(script)
            try:
                self.assertEqual(execute("command-success", ["research_python"], ["fake-command"], root, timeout=10), 0)
            finally:
                if old is None:
                    del runner.ADAPTERS["fake-command"]
                else:
                    runner.ADAPTERS["fake-command"] = old
            result = root / "runs/command-success/research_python/fake-command/result"
            workspace = result.parent / "workspace"
            self.assertEqual(json.loads((workspace / "answer.json").read_text())["n"], 12)
            output = json.loads((result / "stdout.txt").read_text())
            self.assertEqual(Path(output["cwd"]).resolve(), workspace.resolve())
            self.assertEqual(output["prompt"], (workspace / "TASK.md").read_text())
            self.assertEqual((result / "stderr.txt").read_text().strip(), "agent stderr")
            self.assertEqual(json.loads((result / "evaluation.json").read_text())["score"], 5.0)
            record = json.loads((result / "execution.json").read_text())
            self.assertEqual(record["attempt"], 1)
            self.assertFalse(record["retry"])
            self.assertIsNone(record["fallback"])

    def test_timeout_is_recorded_without_retry_or_fallback(self):
        script = "import time; time.sleep(2)"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _copy_frozen_material(root)
            import benchmark.runner as runner
            old = runner.ADAPTERS.get("fake-slow")
            runner.ADAPTERS["fake-slow"] = CommandAgentAdapter(
                name="fake-slow", command_argv=(sys.executable,), fixed_args=("-c", script)
            )
            try:
                self.assertEqual(execute("command-timeout", ["research_python"], ["fake-slow"], root, timeout=1), 1)
            finally:
                if old is None:
                    del runner.ADAPTERS["fake-slow"]
                else:
                    runner.ADAPTERS["fake-slow"] = old
            record = json.loads(
                (root / "runs/command-timeout/research_python/fake-slow/result/execution.json").read_text()
            )
            self.assertTrue(record["timed_out"])
            self.assertEqual(record["exit_code"], None)
            self.assertEqual(record["harness_failure_reasons"], ["timeout", "nonzero_exit"])
            self.assertFalse(record["retry"])
            self.assertIsNone(record["fallback"])

    def test_nonzero_exit_and_missing_executable_are_not_substituted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _copy_frozen_material(root)
            import benchmark.runner as runner
            old = runner.ADAPTERS.get("fake-fail")
            runner.ADAPTERS["fake-fail"] = CommandAgentAdapter(
                name="fake-fail", command_argv=(sys.executable,), fixed_args=("-c", "print('failure', file=__import__('sys').stderr); raise SystemExit(7)")
            )
            try:
                self.assertEqual(execute("command-failure", ["research_python"], ["fake-fail"], root, timeout=10), 1)
            finally:
                if old is None:
                    del runner.ADAPTERS["fake-fail"]
                else:
                    runner.ADAPTERS["fake-fail"] = old
            result = root / "runs/command-failure/research_python/fake-fail/result"
            record = json.loads((result / "execution.json").read_text())
            self.assertEqual(record["exit_code"], 7)
            self.assertEqual((result / "stderr.txt").read_text().strip(), "failure")
            missing = CommandAgentAdapter(name="missing", command_argv=("definitely-not-installed-agent",))
            self.assertEqual(missing.availability()[0], False)
