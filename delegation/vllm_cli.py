"""CLI helpers for the generic ``ask-vllm <named-route>`` command."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import DEFAULT_TIMEOUT_SECONDS
from .vllm import VLLMConfigurationError, VLLMRunResult, run_vllm_consultation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bounded direct OpenAI-compatible vLLM consultation")
    parser.add_argument("route", help="named machine-local vLLM provider route")
    parser.add_argument("--workspace", required=True, type=Path, help="dedicated scoped workspace")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--prompt", help="minimal consultation task text")
    source.add_argument("--prompt-file", type=Path, help="UTF-8 text file containing the task")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-tokens", type=int, help="bounded completion cap (provider cap is enforced)")
    thinking = parser.add_mutually_exclusive_group()
    thinking.add_argument("--thinking", action="store_true", dest="thinking", help="explicitly enable thinking")
    thinking.add_argument("--no-thinking", action="store_false", dest="thinking", help="explicitly disable thinking")
    parser.set_defaults(thinking=None)
    parser.add_argument("--config", type=Path, help="machine-local vLLM TOML (default: XDG config)")
    parser.add_argument("--log-root", type=Path, help="central evidence root")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    task = args.prompt if args.prompt is not None else args.prompt_file.read_text()
    try:
        outcome = run_vllm_consultation(
            args.route, args.workspace, task, timeout_seconds=args.timeout,
            max_tokens=args.max_tokens, thinking=args.thinking, config_path=args.config,
            log_root=args.log_root,
        )
    except (OSError, VLLMConfigurationError) as exc:
        print(f"delegation error: {exc}")
        return 2
    code, record_dir = outcome
    if isinstance(outcome, VLLMRunResult):
        result, diagnostics = outcome.text, outcome.diagnostics
    else:
        # Compatibility for callers/tests that replace the runner with the
        # established two-value evidence shape.
        result = (record_dir / "stdout.txt").read_text()
        diagnostics = (record_dir / "stderr.txt").read_text()
    if result:
        sys.stdout.write(result)
    if diagnostics:
        sys.stderr.write(diagnostics)
    print(f"Delegate: vllm/{args.route}\nExit: {code}\nEvidence: {record_dir}", file=sys.stderr)
    if code == 0 and not result.strip():
        print("delegation response error: vLLM returned no textual consultation", file=sys.stderr)
        return 3
    return code
