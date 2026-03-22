"""Shared todo queue dataclasses."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class TodoItem:
    item_id: str
    priority: int
    cli: str
    project: str
    task: str
    order: int = 0


@dataclass
class PreparedTodoItem:
    item: TodoItem
    cli_key: str
    project_path: str
    project_name: str
    mode: str = "cli"


@dataclass
class TodoValidationIssue:
    item: TodoItem
    message: str


@dataclass
class TodoRunResult:
    item: PreparedTodoItem
    status: str
    duration: float
    summary: str = ""
    returncode: int | None = None
    completed_at: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    )


@dataclass
class TodoQueueStatus:
    is_running: bool
    total: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    pending_items: list[TodoItem] = field(default_factory=list)
    running_items: dict[str, PreparedTodoItem] = field(default_factory=dict)
    current_priority: int | None = None
    started_at: float | None = None

    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        return time.monotonic() - self.started_at
