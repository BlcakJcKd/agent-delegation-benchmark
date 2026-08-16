"""Regression tests for the zero-model-call discovery-subprocess stdin hazard.

Both `delegation.preflight` and `benchmark.preflight` shell out to short-lived
discovery/version/help probes -- including `agy models` -- that are supposed
to make no model call whatsoever. Before this fix, those subprocesses
inherited the caller's stdin; if the caller's stdin had non-empty content
piped into it (e.g. an outer script mid-pipeline), `agy` would read that
content as an inline conversational prompt and make a real model call, even
though the code path is documented and relied upon as "no model invocation".

Every subprocess here is mocked -- these tests never invoke the real `agy`,
`claude`, `codex-deepseek`, etc. binaries, so they cannot themselves trigger
a model call regardless of environment or stdin state.
"""

from __future__ import annotations

import subprocess
import unittest
from unittest.mock import MagicMock, patch

import benchmark.preflight as benchmark_preflight
import delegation.preflight as delegation_preflight
from benchmark.adapters import AntigravityAdapter
from benchmark.tasks import repository_root


def _fake_completed(stdout: str = "", stderr: str = "", returncode: int = 0) -> MagicMock:
    completed = MagicMock()
    completed.returncode = returncode
    completed.stdout = stdout
    completed.stderr = stderr
    return completed


class DelegationPreflightStdinIsolationTests(unittest.TestCase):
    def test_capture_isolates_stdin_with_devnull(self):
        with patch.object(delegation_preflight.subprocess, "run", return_value=_fake_completed("ok")) as mock_run:
            delegation_preflight._capture(["agy", "models"])
        mock_run.assert_called_once()
        self.assertEqual(mock_run.call_args.kwargs.get("stdin"), subprocess.DEVNULL)

    def test_full_check_isolates_stdin_for_every_discovery_subprocess(self):
        # Full check() over every delegate, including the `agy models`
        # probe, with subprocess.run fully mocked: proves the invariant
        # holds end to end, not just for one hand-picked call.
        required_union = {value for values in delegation_preflight.REQUIRED_HELP.values() for value in values}

        def fake_run(command, **kwargs):
            if command[-1] == "models":
                return _fake_completed(stdout="gemini-3.7-flash-medium\tFlash\n")
            if "--version" in command:
                return _fake_completed(stdout="v1")
            return _fake_completed(stdout=" ".join(required_union))

        with patch.object(delegation_preflight.shutil, "which", return_value="/fake/bin"), \
             patch.object(delegation_preflight.subprocess, "run", side_effect=fake_run) as mock_run:
            report = delegation_preflight.check()

        self.assertTrue(report["ok"], report)
        self.assertTrue(mock_run.call_args_list, "expected discovery subprocesses to run")
        for call in mock_run.call_args_list:
            command = call.args[0]
            self.assertEqual(call.kwargs.get("stdin"), subprocess.DEVNULL, f"{command} did not isolate stdin")

    def test_check_never_invokes_a_paid_or_model_subcommand(self):
        with patch.object(delegation_preflight.shutil, "which", return_value="/fake/bin"), \
             patch.object(delegation_preflight.subprocess, "run", return_value=_fake_completed("gemini-3.7-flash-medium")) as mock_run:
            delegation_preflight.check()
        for call in mock_run.call_args_list:
            command = call.args[0]
            self.assertNotIn("run", command)
            self.assertTrue(set(command) & {"--version", "--help", "models"}, command)

    def test_existing_preflight_behavior_is_unchanged_for_flash(self):
        # Mirrors tests/test_delegation.py's existing preflight assertions --
        # confirms the DEVNULL addition did not alter check()'s reported
        # results or the redacted, non-dangerous argv it surfaces.
        def fake_capture(command):
            if command[-1] == "--version":
                return 0, "version"
            if command[-1] == "models":
                return 0, "gemini-3.7-flash-medium\tFlash"
            return 0, " ".join(delegation_preflight.REQUIRED_HELP["flash"])

        with patch.object(delegation_preflight.shutil, "which", return_value="/fake/agy"), \
             patch.object(delegation_preflight, "_capture", side_effect=fake_capture):
            report = delegation_preflight.check(["flash"])
        self.assertTrue(report["ok"])
        argv_check = next(item for item in report["checks"] if item["name"] == "flash: read-only argv")
        self.assertEqual(argv_check["argv"][-1], "<PROMPT>")
        self.assertNotIn("dangerously", " ".join(argv_check["argv"]))


class BenchmarkPreflightStdinIsolationTests(unittest.TestCase):
    def test_capture_isolates_stdin_with_devnull(self):
        with patch.object(benchmark_preflight.subprocess, "run", return_value=_fake_completed("ok")) as mock_run:
            benchmark_preflight._capture(["agy", "models"])
        mock_run.assert_called_once()
        self.assertEqual(mock_run.call_args.kwargs.get("stdin"), subprocess.DEVNULL)

    def test_run_preflight_agy_models_probe_isolates_stdin(self):
        # Exercises the exact `agy models` call path inside run_preflight()
        # (the one reached by `python -m benchmark.runner preflight`, which
        # scripts/run-payg-crossover.sh invokes) using the real
        # AntigravityAdapter, with only its executable-lookup and subprocess
        # calls mocked.
        adapter = AntigravityAdapter(model="gemini-3.7-flash-medium")
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            if command[-1] == "models":
                return _fake_completed(stdout="gemini-3.7-flash-medium\tFlash\n")
            if "--version" in command:
                return _fake_completed(stdout="v1")
            return _fake_completed(stdout=" ".join(benchmark_preflight.HELP_REQUIREMENTS["agy"][0][1]))

        with patch("benchmark.adapters.shutil.which", return_value="/fake/agy"), \
             patch.object(benchmark_preflight.subprocess, "run", side_effect=fake_run):
            report = benchmark_preflight.run_preflight(
                root=repository_root(), task_ids=[], adapters={"agy": adapter}, model_errors=[],
            )

        self.assertTrue(report["ok"], report)
        models_calls = [c for c in calls if c[0][-1] == "models"]
        self.assertTrue(models_calls, "expected the `agy models` discovery probe to run")
        for command, kwargs in calls:
            self.assertEqual(kwargs.get("stdin"), subprocess.DEVNULL, f"{command} did not isolate stdin")

    def test_run_preflight_never_invokes_a_paid_or_model_subcommand(self):
        adapter = AntigravityAdapter(model="gemini-3.7-flash-medium")
        with patch("benchmark.adapters.shutil.which", return_value="/fake/agy"), \
             patch.object(benchmark_preflight.subprocess, "run", return_value=_fake_completed("gemini-3.7-flash-medium")) as mock_run:
            benchmark_preflight.run_preflight(
                root=repository_root(), task_ids=[], adapters={"agy": adapter}, model_errors=[],
            )
        for call in mock_run.call_args_list:
            command = call.args[0]
            self.assertNotIn("run", command)


if __name__ == "__main__":
    unittest.main()
