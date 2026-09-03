from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path


CLAUDE_TASK_ALLOWED_TOOLS: dict[str, tuple[str, ...]] = {
    "research_python": ("Read", "Glob", "Grep", "Write", "Edit", "Bash(python *)", "Bash(python3 *)"),
    "diagnostic_plot": ("Read", "Glob", "Grep", "Write", "Edit", "Bash(python *)", "Bash(python3 *)"),
    "debug_package": ("Read", "Glob", "Grep", "Write", "Edit", "Bash(python *)", "Bash(python3 *)", "Bash(pytest *)"),
}
AGY_REASONING_EFFORTS = ("low", "medium", "high")


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
    reasoning_effort: str | None = None

    @property
    def executable(self) -> str:
        return "agy"

    def command(self, workspace: Path, prompt: str, output_dir: Path, task_id: str | None = None) -> list[str]:
        if self.reasoning_effort is not None and self.reasoning_effort not in AGY_REASONING_EFFORTS:
            raise ValueError(f"unsupported AGY reasoning effort {self.reasoning_effort!r}; supported: {list(AGY_REASONING_EFFORTS)!r}")
        command = [
            "agy", "--output-format", "json", "--mode", "accept-edits", "--sandbox", "--add-dir", str(workspace),
        ]
        if self.model:
            command.extend(["--model", self.model])
        if self.reasoning_effort:
            command.extend(["--effort", self.reasoning_effort])
        # agy's print flag is placed immediately before the final prompt.
        return [*command, "-p", prompt]

    def describe(self, task_id: str | None = None) -> dict[str, object]:
        return {
            **super().describe(),
            "sandbox": "agy --sandbox",
            "permission_mode": "accept-edits (only non-bypass mode documented)",
            "reasoning_effort": self.reasoning_effort,
            "output": "JSON requested",
        }


@dataclass(frozen=True)
class DeepSeekAdapter(Adapter):
    """PAYG candidate via the codex-deepseek provider-profile launcher.

    Same transport shape as CodexAdapter (`exec --sandbox workspace-write`),
    routed through the independently verified `codex-deepseek` launcher
    (pinned `--profile deepseek`, keyring credential retrieval) rather than
    normal OpenAI Codex -- see docs/PAYG_DELEGATES.md. `name` varies per
    registration (deepseek-pro / deepseek-flash share this one class with
    different pinned models). Reasoning effort is fixed at "high" -- DeepSeek's
    own catalog default and this project's pinned delegation-layer choice
    (`delegation.core.DELEGATES`); it is not a benchmark-time configurable
    knob, so there is no `--deepseek-reasoning-effort` flag to silently vary.
    """

    name: str = "deepseek-pro"

    @property
    def executable(self) -> str:
        return "codex-deepseek"

    def command(self, workspace: Path, prompt: str, output_dir: Path, task_id: str | None = None) -> list[str]:
        command = [
            "codex-deepseek", "exec", "--ephemeral", "--skip-git-repo-check",
            "--sandbox", "workspace-write",
            "--cd", str(workspace), "--json",
            "--output-last-message", str(output_dir / "last_message.txt"),
        ]
        if self.model:
            command.extend(["--model", self.model])
        command.extend(["--config", 'model_reasoning_effort="high"'])
        return [*command, prompt]

    def describe(self, task_id: str | None = None) -> dict[str, object]:
        return {
            **super().describe(),
            "provider": "deepseek",
            "transport": "codex",
            "billing": "payg",
            "maturity": "experimental",
            "sandbox": "workspace-write",
            "approval": "no automatic approval override",
            "reasoning_effort": "high",
            "output": "JSONL",
        }


@dataclass(frozen=True)
class MiniMaxAdapter(Adapter):
    """PAYG candidate via the codex-minimax provider-profile launcher.

    See DeepSeekAdapter -- identical transport shape, routed through
    `codex-minimax` (pinned `--profile minimax`) instead. Reasoning effort is
    fixed at "high", MiniMax's own catalog default and the value its local
    profile (`~/.codex/minimax.config.toml`) already used.
    """

    name: str = "minimax-m3"

    @property
    def executable(self) -> str:
        return "codex-minimax"

    def command(self, workspace: Path, prompt: str, output_dir: Path, task_id: str | None = None) -> list[str]:
        command = [
            "codex-minimax", "exec", "--ephemeral", "--skip-git-repo-check",
            "--sandbox", "workspace-write",
            "--cd", str(workspace), "--json",
            "--output-last-message", str(output_dir / "last_message.txt"),
        ]
        if self.model:
            command.extend(["--model", self.model])
        command.extend(["--config", 'model_reasoning_effort="high"'])
        return [*command, prompt]

    def describe(self, task_id: str | None = None) -> dict[str, object]:
        return {
            **super().describe(),
            "provider": "minimax",
            "transport": "codex",
            "billing": "payg",
            "maturity": "experimental",
            "sandbox": "workspace-write",
            "approval": "no automatic approval override",
            "reasoning_effort": "high",
            "output": "JSONL",
        }


@dataclass(frozen=True)
class CommandAgentAdapter(Adapter):
    """Run a machine-local coding-agent command in the task workspace."""

    command_argv: tuple[str, ...] = field(default_factory=tuple)
    fixed_args: tuple[str, ...] = field(default_factory=tuple)

    @property
    def executable(self) -> str:
        return self.command_argv[0] if self.command_argv else ""

    def command(self, workspace: Path, prompt: str, output_dir: Path, task_id: str | None = None) -> list[str]:
        return [*self.command_argv, *self.fixed_args, prompt]

    def describe(self, task_id: str | None = None) -> dict[str, object]:
        return {
            **super().describe(),
            "adapter": "command-agent",
            "command_executable": self.executable,
            "fixed_argument_count": len(self.fixed_args),
            "cwd": "benchmark task workspace",
            "prompt_delivery": "final argv item",
            "output": "captured stdout/stderr",
        }


ADAPTERS: dict[str, Adapter] = {
    "codex": CodexAdapter(),
    "claude": ClaudeAdapter(),
    "agy": AntigravityAdapter(),
    "deepseek-pro": DeepSeekAdapter(name="deepseek-pro"),
    "deepseek-flash": DeepSeekAdapter(name="deepseek-flash"),
    "minimax-m3": MiniMaxAdapter(),
}


def configured_adapters(
    models: dict[str, str],
    codex_reasoning_effort: str | None = None,
    claude_reasoning_effort: str | None = None,
    agy_reasoning_effort: str | None = None,
) -> dict[str, Adapter]:
    """Return fresh adapters with explicitly requested models."""
    return {
        "codex": CodexAdapter(model=models.get("codex"), reasoning_effort=codex_reasoning_effort),
        "claude": ClaudeAdapter(model=models.get("claude"), reasoning_effort=claude_reasoning_effort),
        "agy": AntigravityAdapter(model=models.get("agy"), reasoning_effort=agy_reasoning_effort),
        "deepseek-pro": DeepSeekAdapter(name="deepseek-pro", model=models.get("deepseek-pro")),
        "deepseek-flash": DeepSeekAdapter(name="deepseek-flash", model=models.get("deepseek-flash")),
        "minimax-m3": MiniMaxAdapter(model=models.get("minimax-m3")),
    }
