import unittest
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

from benchmark.v2.gemini_experiment import assess_agy_isolation_boundary, harness_preflight


class GeminiIsolationTests(unittest.TestCase):
    def test_agy_native_sandbox_is_not_independent_tool_boundary(self):
        result = assess_agy_isolation_boundary(
            version="1.1.25",
            help_text="--sandbox  --add-dir DIR  --model MODEL  --effort low|medium|high",
        )
        self.assertEqual(result["status"], "invalid")
        self.assertFalse(result["provider_transport_separable"])
        self.assertFalse(result["candidate_tool_subprocess_sandbox"])
        self.assertFalse(result["documented_independent_boundary"])

    def test_undocumented_boundary_markers_do_not_make_implementation_safe(self):
        result = assess_agy_isolation_boundary(
            version="1.1.25",
            help_text="tool subprocess executor is mentioned, but no attachable implementation exists",
        )
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(result["documented_independent_boundary"])
        self.assertFalse(result["candidate_tool_subprocess_sandbox"])

    @unittest.skipUnless(shutil.which("bwrap"), "bwrap is not installed")
    def test_bwrap_fixture_contains_filesystem_symlink_and_network(self):
        with tempfile.TemporaryDirectory(prefix="ekalavya-bwrap-test-") as raw:
            root = Path(raw)
            workspace = root / "workspace"
            parent = root / "parent"
            workspace.mkdir()
            parent.mkdir()
            (parent / "sentinel").write_text("private\n")
            (workspace / "parent-link").symlink_to(parent, target_is_directory=True)
            command = [
                "bwrap", "--die-with-parent", "--new-session",
                "--unshare-user", "--unshare-pid", "--unshare-net",
                "--ro-bind", "/usr", "/usr", "--ro-bind", "/bin", "/bin",
                "--ro-bind", "/lib", "/lib", "--ro-bind", "/lib64", "/lib64",
                "--dev", "/dev", "--proc", "/proc", "--tmpfs", "/tmp",
                "--bind", str(workspace), "/workspace", "--chdir", "/workspace",
                "--", "/bin/sh", "-c",
                "set -eu; printf allowed > /workspace/write-ok; "
                "test -r /workspace/write-ok; "
                "test ! -r /workspace/parent-link/sentinel; "
                "test ! -r /etc/hostname; "
                "python3 -c 'import socket; s=socket.create_connection((\"1.1.1.1\",443),1)' 2>/dev/null && exit 9 || true",
            ]
            completed = subprocess.run(command, text=True, capture_output=True, timeout=10)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual((workspace / "write-ok").read_text(), "allowed")

    def test_harness_preflight_has_no_provider_call(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if command == ["agy", "--version"]:
                return 0, "1.1.25\n", ""
            if command == ["agy", "--help"]:
                return 0, "--sandbox --add-dir --model --effort", ""
            if command == ["opencode", "models"]:
                return 0, "", ""
            if command == ["opencode", "--version"]:
                return 0, "1.17.2\n", ""
            raise AssertionError(command)

        with patch("benchmark.v2.gemini_experiment.run_command", side_effect=fake_run):
            result = harness_preflight(persist=False)
        self.assertEqual(result["agy"]["status"], "invalid")
        self.assertEqual(result["agy"]["probe"], "not_run_by_zero_inference_preflight")
        self.assertFalse(any("-p" in call for call in calls))


if __name__ == "__main__":
    unittest.main()
