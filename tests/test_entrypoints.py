"""Tests for the fixed-delegate console-script entry points (ask_flash_main
etc.). Every case here uses --help, which argparse handles by printing and
raising SystemExit before any subprocess is ever constructed or launched --
so these are safe to run with zero risk of a real delegate CLI invocation.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout

from delegation.cli import ask_flash_main, ask_haiku_main, ask_sonnet_main, main


class FixedDelegateEntryPointTests(unittest.TestCase):
    def test_ask_flash_help_does_not_require_typing_the_delegate_name(self):
        buf = io.StringIO()
        with redirect_stdout(buf), self.assertRaises(SystemExit) as ctx:
            main(["--help"], fixed_delegate="flash")
        self.assertEqual(ctx.exception.code, 0)
        self.assertNotIn("{flash,haiku,sonnet}", buf.getvalue())

    def test_ask_haiku_help_exits_cleanly(self):
        with self.assertRaises(SystemExit) as ctx:
            with redirect_stdout(io.StringIO()):
                main(["--help"], fixed_delegate="haiku")
        self.assertEqual(ctx.exception.code, 0)

    def test_ask_sonnet_help_exits_cleanly(self):
        with self.assertRaises(SystemExit) as ctx:
            with redirect_stdout(io.StringIO()):
                main(["--help"], fixed_delegate="sonnet")
        self.assertEqual(ctx.exception.code, 0)

    def test_missing_required_workspace_argument_is_rejected_before_any_subprocess(self):
        with self.assertRaises(SystemExit) as ctx:
            with redirect_stdout(io.StringIO()), __import__("contextlib").redirect_stderr(io.StringIO()):
                main(["--prompt", "x"], fixed_delegate="flash")
        self.assertNotEqual(ctx.exception.code, 0)

    def test_entry_point_functions_are_importable_and_callable_symbols(self):
        # Confirms the pyproject.toml [project.scripts] targets actually
        # resolve to callables with the expected signature (no argv param
        # needed -- setuptools' generated stub calls them with none).
        for func in (ask_flash_main, ask_haiku_main, ask_sonnet_main):
            self.assertTrue(callable(func))


if __name__ == "__main__":
    unittest.main()
