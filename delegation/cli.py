"""CLI entry point for operational, read-only delegated consultation.

Two shapes share this module: the module-style invocation used for
development (``python -m delegation.cli flash --workspace ...``, still how
``bin/ask-flash`` runs) and the installed ``ask-flash``/``ask-haiku``/
``ask-sonnet`` console scripts, which fix the delegate name so a user never
types it (see ``ask_flash_main`` etc.).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import DELEGATES, DEFAULT_TIMEOUT_SECONDS, run_consultation


def _parser(*, fixed_delegate: str | None = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safe, read-only delegated consultation")
    if fixed_delegate is None:
        parser.add_argument("delegate", choices=tuple(DELEGATES))
    parser.add_argument("--workspace", required=True, type=Path, help="dedicated scoped workspace")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--prompt", help="consultation task text")
    source.add_argument("--prompt-file", type=Path, help="UTF-8 text file containing consultation task")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--log-root", type=Path, help="central log root; never defaults inside workspace")
    parser.add_argument(
        "--caller",
        help=(
            "provenance-only identifier for the primary agent, e.g. codex, claude-code, "
            "manual; falls back to $AGENT_DELEGATION_CALLER, then 'unknown'"
        ),
    )
    parser.add_argument(
        "--primary",
        help=(
            "declared primary provider identity, e.g. claude-code, codex, gemini, manual; "
            "enforced by the self-provider guard (same-provider external delegation is "
            "rejected) and recorded for audit. Omit if unknown -- unenforced, not assumed."
        ),
    )
    return parser


def main(argv: list[str] | None = None, *, fixed_delegate: str | None = None) -> int:
    args = _parser(fixed_delegate=fixed_delegate).parse_args(argv)
    delegate = fixed_delegate or args.delegate
    task = args.prompt if args.prompt is not None else args.prompt_file.read_text()
    try:
        code, record_dir = run_consultation(
            delegate, args.workspace, task,
            timeout_seconds=args.timeout, log_root=args.log_root,
            caller=args.caller, primary=args.primary,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        # Preserve the established validation/setup error channel for existing
        # CLI consumers. Successful consultations use stdout exclusively for
        # the delegate result; these errors have no consultation result.
        print(f"delegation error: {exc}")
        return 2

    # stdout is the consultation result channel.  The delegate's raw result
    # is already persisted as stdout.txt; replay it unchanged so callers do
    # not need to discover or parse an audit directory just to consume a
    # successful response.  Keep operational metadata and diagnostics on
    # stderr so existing human-readable evidence remains available without
    # contaminating the result stream.
    result = (record_dir / "stdout.txt").read_text()
    diagnostics = (record_dir / "stderr.txt").read_text()
    if result:
        sys.stdout.write(result)
    if diagnostics:
        sys.stderr.write(diagnostics)
        if not diagnostics.endswith("\n"):
            sys.stderr.write("\n")
    print(f"Delegate: {delegate}\nExit: {code}\nEvidence: {record_dir}", file=sys.stderr)
    if code == 0 and not result.strip():
        print(
            "delegation response error: delegate exited 0 but returned no textual consultation; "
            "classify as model/response failure",
            file=sys.stderr,
        )
        return 3
    return code


def ask_flash_main() -> int:
    return main(fixed_delegate="flash")


def ask_haiku_main() -> int:
    return main(fixed_delegate="haiku")


def ask_sonnet_main() -> int:
    return main(fixed_delegate="sonnet")


def ask_terra_main() -> int:
    return main(fixed_delegate="terra")


def ask_luna_main() -> int:
    return main(fixed_delegate="luna")


def ask_deepseek_pro_main() -> int:
    return main(fixed_delegate="deepseek-pro")


def ask_deepseek_flash_main() -> int:
    return main(fixed_delegate="deepseek-flash")


def ask_minimax_m3_main() -> int:
    return main(fixed_delegate="minimax-m3")


if __name__ == "__main__":
    raise SystemExit(main())
