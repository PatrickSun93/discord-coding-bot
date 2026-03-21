"""Abstract base class for CLI adapters."""

from __future__ import annotations

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
