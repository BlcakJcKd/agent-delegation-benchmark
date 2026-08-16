"""Argument-handling regression tests for scripts/run-payg-crossover.sh.

These invoke the real launcher script as a subprocess -- not a
reimplementation of its parsing -- so a regression in the actual bash file
is caught. To keep the tests fast, portable (no dependency on `agy`,
`codex-deepseek`, etc. being installed), and non-recursive (the real script
shells out to `python -m unittest discover -s tests -q`, which would
otherwise re-run this very test file), a stub `python` shim is placed first
on PATH. It logs every invocation and never performs a paid run.

Every case here either exits before the script reaches the no-model checks
(--help, unknown option, missing --run-label value) or reaches the
confirmation prompt and is given a closed stdin (immediate EOF), which the
script's `read` treats as "anything other than 'run'" -- i.e. abort. No case
ever supplies stdin content, because piped content can flow through to a
live `agy models` call inside delegation.preflight (see incident note in
the task this file was written for) -- DEVNULL is the only safe choice.
"""

from __future__ import annotations

import os
import stat
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "run-payg-crossover.sh"

FAKE_PYTHON = """#!/usr/bin/env bash
echo "python $*" >> "$FAKE_PYTHON_LOG"
case "$*" in
  *"benchmark.runner run"*)
    touch "$FAKE_PAID_RUN_MARKER"
    ;;
esac
exit 0
"""


class RunPaygCrossoverCliTests(unittest.TestCase):
    def _run(self, *args: str, fake_bin: Path, log: Path, marker: Path) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PATH"] = f"{fake_bin}:{env['PATH']}"
        env["FAKE_PYTHON_LOG"] = str(log)
        env["FAKE_PAID_RUN_MARKER"] = str(marker)
        return subprocess.run(
            [str(SCRIPT), *args],
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=15,
            env=env,
        )

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.fake_bin = root / "bin"
        self.fake_bin.mkdir()
        python_shim = self.fake_bin / "python"
        python_shim.write_text(FAKE_PYTHON)
        python_shim.chmod(python_shim.stat().st_mode | stat.S_IEXEC)
        self.log = root / "python.log"
        self.marker = root / "PAID_RUN_INVOKED"

    def test_help_exits_zero_without_running_checks_or_preflight(self):
        result = self._run("--help", fake_bin=self.fake_bin, log=self.log, marker=self.marker)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Usage: run-payg-crossover.sh", result.stdout)
        self.assertNotIn("== no-model checks ==", result.stdout)
        self.assertFalse(self.log.exists(), "stub python should never be invoked for --help")
        self.assertFalse(self.marker.exists())

    def test_short_help_flag_also_exits_zero(self):
        result = self._run("-h", fake_bin=self.fake_bin, log=self.log, marker=self.marker)
        self.assertEqual(result.returncode, 0)
        self.assertIn("Usage: run-payg-crossover.sh", result.stdout)
        self.assertFalse(self.log.exists())

    def test_valid_explicit_run_label_reaches_confirmation_and_safely_aborts(self):
        result = self._run(
            "--run-label", "payg-crossover-regtest-001",
            fake_bin=self.fake_bin, log=self.log, marker=self.marker,
        )
        self.assertIn("run label: payg-crossover-regtest-001", result.stdout)
        self.assertIn("Aborted; no model call made.", result.stdout)
        self.assertEqual(result.returncode, 1)
        log_text = self.log.read_text()
        self.assertIn("unittest discover", log_text)
        self.assertIn("delegation.preflight", log_text)
        self.assertIn("benchmark.runner preflight", log_text)
        self.assertFalse(self.marker.exists(), "confirmation was not accepted; paid run must not fire")

    def test_run_label_equals_syntax_is_accepted(self):
        result = self._run(
            "--run-label=payg-crossover-regtest-002",
            fake_bin=self.fake_bin, log=self.log, marker=self.marker,
        )
        self.assertIn("run label: payg-crossover-regtest-002", result.stdout)
        self.assertEqual(result.returncode, 1)
        self.assertFalse(self.marker.exists())

    def test_unknown_option_is_rejected_without_running_checks(self):
        result = self._run("--bogus", fake_bin=self.fake_bin, log=self.log, marker=self.marker)
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown option", result.stderr)
        self.assertFalse(self.log.exists(), "stub python should never be invoked for an unknown option")
        self.assertFalse(self.marker.exists())

    def test_unexpected_positional_argument_is_rejected(self):
        result = self._run("some-label", fake_bin=self.fake_bin, log=self.log, marker=self.marker)
        self.assertEqual(result.returncode, 2)
        self.assertIn("unexpected argument", result.stderr)
        self.assertFalse(self.log.exists())

    def test_missing_run_label_value_is_rejected(self):
        result = self._run("--run-label", fake_bin=self.fake_bin, log=self.log, marker=self.marker)
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires a value", result.stderr)
        self.assertFalse(self.log.exists())

    def test_run_label_beginning_with_dash_is_rejected(self):
        result = self._run(
            "--run-label", "--help",
            fake_bin=self.fake_bin, log=self.log, marker=self.marker,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("must not start with '-'", result.stderr)
        self.assertFalse(self.log.exists())
        self.assertFalse(self.marker.exists())


if __name__ == "__main__":
    unittest.main()
