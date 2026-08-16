from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path


CLAUDE_TASK_ALLOWED_TOOLS: dict[str, tuple[str, ...]] = {
    "research_python": ("Read", "Glob", "Grep", "Write", "Edit", "Bash(python *)", "Bash(python3 *)"),
    "diagnostic_plot": ("Read", "Glob", "Grep", "Write", "Edit", "Bash(python *)", "Bash(python3 *)"),
    "debug_package": ("Read", "Glob", "Grep", "Write", "Edit", "Bash(python *)", "Bash(python3 *)", "Bash(pytest *)"),
}


@dataclass(frozen=True)
class Adapter:
    """A local CLI invocation. Commands are argv lists, never shell strings."""

    name: str
    model: str | None = None

    def command(self, workspace: Path, prompt: str, output_dir: Path, task_id: str | None = None) -> list[str]:
        raise NotImplementedError

    def availability(self) -> tuple[bool, str]:
        path = shutil.which(self.executable)
        if not path:
            return False, f"{self.executable!r} is not on PATH"
        return True, path

    def describe(self, task_id: str | None = None) -> dict[str, object]:
        return {"agent": self.name, "requested_model": self.model}

    @property
    def executable(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class CodexAdapter(Adapter):
    name: str = field(default="codex", init=False)
    reasoning_effort: str | None = None

    @property
    def executable(self) -> str:
        return "codex"

    def command(self, workspace: Path, prompt: str, output_dir: Path, task_id: str | None = None) -> list[str]:
        command = [
            "codex", "exec", "--ephemeral", "--skip-git-repo-check",
            "--sandbox", "workspace-write",
            "--cd", str(workspace), "--json",
            "--output-last-message", str(output_dir / "last_message.txt"),
        ]
        if self.model:
            command.extend(["--model", self.model])
        if self.reasoning_effort:
            command.extend(["--config", f'model_reasoning_effort="{self.reasoning_effort}"'])
        return [*command, prompt]

    def describe(self, task_id: str | None = None) -> dict[str, object]:
        return {
            **super().describe(),
            "sandbox": "workspace-write",
            "approval": "no automatic approval override",
            "reasoning_effort": self.reasoning_effort,
            "output": "JSONL",
        }


@dataclass(frozen=True)
class ClaudeAdapter(Adapter):
    name: str = field(default="claude", init=False)
    reasoning_effort: str | None = None

    @property
    def executable(self) -> str:
        return "claude"

    def command(self, workspace: Path, prompt: str, output_dir: Path, task_id: str | None = None) -> list[str]:
        command = [
            "claude", "--output-format", "json", "--no-session-persistence",
            "--safe-mode", "--permission-mode", "auto",
        ]
        allowed_tools = CLAUDE_TASK_ALLOWED_TOOLS.get(task_id or "", ())
        if allowed_tools:
            # Help documents comma-separated tools; preserve the entire list as one argv item.
            command.extend(["--allowedTools", ",".join(allowed_tools)])
        if self.model:
            command.extend(["--model", self.model])
        if self.reasoning_effort:
            command.extend(["--effort", self.reasoning_effort])
        # The prompt is deliberately the final argv element.
        return [*command, "-p", prompt]

    def describe(self, task_id: str | None = None) -> dict[str, object]:
        return {
            **super().describe(),
            "sandbox": "process cwd only (no equivalent CLI workspace sandbox documented)",
            "permission_mode": "auto",
            "reasoning_effort": self.reasoning_effort,
            "allowed_tools": list(CLAUDE_TASK_ALLOWED_TOOLS.get(task_id or "", ())),
            "output": "JSON",
        }


@dataclass(frozen=True)
class AntigravityAdapter(Adapter):
    name: str = field(default="agy", init=False)

    @property
    def executable(self) -> str:
        return "agy"

    def command(self, workspace: Path, prompt: str, output_dir: Path, task_id: str | None = None) -> list[str]:
        command = [
            "agy", "--output-format", "json", "--mode", "accept-edits", "--sandbox",
        ]
        if self.model:
            command.extend(["--model", self.model])
        # agy's print flag is placed immediately before the final prompt.
        return [*command, "-p", prompt]

    def describe(self, task_id: str | None = None) -> dict[str, object]:
        return {
            **super().describe(),
            "sandbox": "agy --sandbox",
            "permission_mode": "accept-edits (only non-bypass mode documented)",
            "output": "JSON requested",
        }


ADAPTERS: dict[str, Adapter] = {
    "codex": CodexAdapter(),
    "claude": ClaudeAdapter(),
    "agy": AntigravityAdapter(),
}


def configured_adapters(
    models: dict[str, str],
    codex_reasoning_effort: str | None = None,
    claude_reasoning_effort: str | None = None,
) -> dict[str, Adapter]:
    """Return fresh adapters with explicitly requested models."""
    return {
        "codex": CodexAdapter(model=models.get("codex"), reasoning_effort=codex_reasoning_effort),
        "claude": ClaudeAdapter(model=models.get("claude"), reasoning_effort=claude_reasoning_effort),
        "agy": AntigravityAdapter(model=models.get("agy")),
    }
