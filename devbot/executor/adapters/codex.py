"""Codex CLI adapter (OpenAI Codex)."""

from __future__ import annotations

from devbot.executor.adapters.base import BaseCLIAdapter


class CodexAdapter(BaseCLIAdapter):
    name = "codex"

    def __init__(
        self,
        command: str = "codex",
        base_args: list[str] | None = None,
        autonomy_args: list[str] | None = None,
        extra_args: list[str] | None = None,
    ):
        self.command = command
        self.base_args = base_args if base_args is not None else ["exec", "--json"]
        self.autonomy_args = autonomy_args if autonomy_args is not None else ["--full-auto"]
        self.extra_args = ["--skip-git-repo-check"] if extra_args is None else extra_args

    def build_command(self, task: str, project_path: str) -> list[str]:
        return [self.resolved_command()] + self.base_args + self.autonomy_args + self.extra_args + [self.prepare_task_argument(task)]
