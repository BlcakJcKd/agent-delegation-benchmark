"""No-inference validation and private pilot helpers for Benchmark V2."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import CODING_FAMILIES
from .generate import make_instance, manifest, materialize
from .validate import frozen_manifest, validate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark V2 controller")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="generate, evaluate, and freeze without model inference")
    check.add_argument("--seed", type=int, default=20260903)
    gen = sub.add_parser("generate", help="materialize candidate tasks")
    gen.add_argument("directory", type=Path); gen.add_argument("--seed", type=int, default=20260903)
    args = parser.parse_args(argv)
    if args.command == "check":
        result = validate(Path.cwd(), args.seed); result["freeze"] = frozen_manifest(Path.cwd(), args.seed)
        print(json.dumps(result, indent=2, sort_keys=True)); return 0 if result["ok"] else 1
    args.directory.mkdir(parents=True, exist_ok=True)
    instances = [make_instance(family, args.seed + i) for i, family in enumerate(CODING_FAMILIES)]
    for instance in instances: materialize(instance, args.directory / instance.task_id.replace("@", "-"))
    (args.directory / "manifest.json").write_text(json.dumps(manifest(instances), indent=2) + "\n")
    print(json.dumps({"directory": str(args.directory), "tasks": [i.task_id for i in instances]}, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())

