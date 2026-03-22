"""Abstract base class for CLI adapters."""

from __future__ import annotations

import os
import shutil
from abc import ABC, abstractmethod


class BaseCLIAdapter(ABC):
    name: str
    command: str

    @abstractmethod
    def build_command(self, task: str, project_path: str) -> list[str]:
        """Return the full CLI command as a list of args."""
        ...

    def is_available(self) -> bool:
        """Check if the CLI binary exists on PATH."""
        return shutil.which(self.command) is not None

    def resolved_command(self) -> str:
        """Return an executable path suitable for subprocess execution."""
        return shutil.which(self.command) or self.command

    def prepare_task_argument(self, task: str) -> str:
        """Normalize prompt text for CLIs launched through Windows wrapper scripts."""
        command = self.resolved_command().lower()
        if os.name == "nt" and command.endswith((".cmd", ".bat")):
            return task.replace("\r\n", "\n").replace("\n", "\\n")
        return task
