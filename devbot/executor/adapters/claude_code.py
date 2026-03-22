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
        self.base_args = base_args if base_args is not None else ["-p", "--output-format", "stream-json", "--verbose"]
        self.autonomy_args = autonomy_args if autonomy_args is not None else ["--dangerously-skip-permissions"]
        self.extra_args = extra_args or []

    def build_command(self, task: str, project_path: str) -> list[str]:
        task_arg = self.prepare_task_argument(task)
        args = list(self.base_args)
        for index, token in enumerate(args):
            if token in {"-p", "--prompt"}:
                args.insert(index + 1, task_arg)
                return [self.resolved_command()] + args + self.autonomy_args + self.extra_args
        return [self.resolved_command()] + args + self.autonomy_args + self.extra_args + [task_arg]
