"""Claude Code CLI adapter."""

from __future__ import annotations

from devbot.executor.adapters.base import BaseCLIAdapter


class ClaudeCodeAdapter(BaseCLIAdapter):
    name = "claude_code"

    def __init__(
        self,
        command: str = "claude",
        base_args: list[str] | None = None,
        autonomy_args: list[str] | None = None,
        extra_args: list[str] | None = None,
    ):
        self.command = command
        self.base_args = base_args if base_args is not None else ["-p", "--output-format", "stream-json"]
        self.autonomy_args = autonomy_args if autonomy_args is not None else ["--dangerously-skip-permissions"]
        self.extra_args = extra_args or []

    def build_command(self, task: str, project_path: str) -> list[str]:
        return [self.command] + self.base_args + self.autonomy_args + self.extra_args + [task]
