"""No-model validation for the operational consultation wrappers."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from .core import DELEGATES, build_argv


REQUIRED_HELP: dict[str, tuple[str, ...]] = {
    "flash": ("--mode", "plan", "--sandbox", "--model", "--effort", "--print"),
    "haiku": ("--permission-mode", "plan", "--tools", "--allowedTools", "--safe-mode", "--effort", "--print"),
    "sonnet": ("--permission-mode", "plan", "--tools", "--allowedTools", "--safe-mode", "--effort", "--print"),
}


def _capture(command: list[str]) -> tuple[int, str]:
    completed = subprocess.run(command, text=True, capture_output=True)
    return completed.returncode, completed.stdout + completed.stderr


def check(delegates: list[str] | None = None) -> dict[str, object]:
    selected = delegates or list(DELEGATES)
    checks: list[dict[str, object]] = []
    for name in selected:
        spec = DELEGATES[name]
        executable = shutil.which(spec.executable)
        checks.append({"name": name + ": executable", "ok": bool(executable), "detail": executable or "MISSING"})
        if not executable:
            continue
        code, version = _capture([spec.executable, "--version"])
        checks.append({"name": name + ": version", "ok": code == 0, "detail": version.strip()})
        code, help_text = _capture([spec.executable, "--help"])
        missing = [value for value in REQUIRED_HELP[name] if value not in help_text]
        checks.append({"name": name + ": supported read-only flags", "ok": code == 0 and not missing, "detail": "OK" if not missing else "missing: " + ", ".join(missing)})
        command = build_argv(spec, Path("<WORKSPACE>"), "<PROMPT>")
        dangerous = [value for value in command if "dangerously" in value or "bypass" in value or value == "danger-full-access"]
        checks.append({
            "name": name + ": read-only argv", "ok": not dangerous and command[-1].endswith("<PROMPT>\n"),
            "detail": "OK" if not dangerous else "dangerous arguments: " + ", ".join(dangerous),
            "argv": command[:-1] + ["<PROMPT>"],
        })
    if "flash" in selected and shutil.which("agy"):
        code, models = _capture(["agy", "models"])
        checks.append({"name": "flash: requested model", "ok": code == 0 and DELEGATES["flash"].model in models, "detail": DELEGATES["flash"].model})
    return {"ok": all(bool(item["ok"]) for item in checks), "checks": checks}


def main(argv: list[str] | None = None) -> int:
    selected = argv or list(DELEGATES)
    unknown = sorted(set(selected) - set(DELEGATES))
    if unknown:
        print("unknown delegates: " + ", ".join(unknown), file=sys.stderr)
        return 2
    report = check(selected)
    print("Delegation preflight (no model invocation)")
    for item in report["checks"]:
        marker = "PASS" if item["ok"] else "FAIL"
        print(f"  [{marker}] {item['name']}: {item['detail']}")
        if "argv" in item:
            print("         argv=" + json.dumps(item["argv"]))
    print("Delegation preflight: " + ("PASS" if report["ok"] else "FAIL"))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
