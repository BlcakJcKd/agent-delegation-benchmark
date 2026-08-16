"""CLI entry point for operational, read-only delegated consultation."""

from __future__ import annotations

import argparse
from pathlib import Path

from .core import DELEGATES, DEFAULT_TIMEOUT_SECONDS, run_consultation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safe, read-only delegated consultation")
    parser.add_argument("delegate", choices=tuple(DELEGATES))
    parser.add_argument("--workspace", required=True, type=Path, help="dedicated scoped workspace")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--prompt", help="consultation task text")
    source.add_argument("--prompt-file", type=Path, help="UTF-8 text file containing consultation task")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--log-root", type=Path, help="central log root; never defaults inside workspace")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    task = args.prompt if args.prompt is not None else args.prompt_file.read_text()
    try:
        code, record_dir = run_consultation(
            args.delegate, args.workspace, task,
            timeout_seconds=args.timeout, log_root=args.log_root,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"delegation error: {exc}")
        return 2
    print(f"Delegate: {args.delegate}\nExit: {code}\nEvidence: {record_dir}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
