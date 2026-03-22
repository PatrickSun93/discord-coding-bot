"""Todo queue executor."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import discord

from devbot.todo.archiver import archive_todo_result
from devbot.todo.models import PreparedTodoItem, TodoQueueStatus, TodoRunResult
from devbot.todo.parser import parse_todo_file, remove_todo_item
from devbot.todo.validator import prepare_todo_items

if TYPE_CHECKING:
    from devbot.config.settings import Config
    from devbot.executor.manager import TaskManager

logger = logging.getLogger(__name__)


class TodoExecutor:
    def __init__(self, config: "Config", task_manager: "TaskManager"):
        self.config = config
        self.task_manager = task_manager
        self._run_task: asyncio.Task | None = None
        self._stop_requested = False
        self._pending: list[PreparedTodoItem] = []
        self._active: dict[str, PreparedTodoItem] = {}
        self._active_projects: set[str] = set()
        self._task_lookup: dict[asyncio.Task, str] = {}
        self._started_at: float | None = None
        self._current_priority: int | None = None
        self._total = 0
        self._completed = 0
        self._failed = 0
        self._cancelled = 0
        self._lock = asyncio.Lock()

    def is_running(self) -> bool:
        return self._run_task is not None and not self._run_task.done()

    @property
    def stop_requested(self) -> bool:
        return self._stop_requested

    def status(self) -> TodoQueueStatus:
        pending_items = [prepared.item for prepared in self._pending]
        if not self.is_running():
            pending_items = parse_todo_file(self.config.todo.file)
        return TodoQueueStatus(
            is_running=self.is_running(),
            total=self._total if self.is_running() else len(pending_items),
            completed=self._completed,
            failed=self._failed,
            cancelled=self._cancelled,
            pending_items=pending_items,
            running_items=dict(self._active),
            current_priority=self._current_priority,
            started_at=self._started_at,
        )

    async def start(
        self,
        channel: discord.abc.Messageable,
        runner: Callable[[PreparedTodoItem, discord.abc.Messageable], Awaitable[TodoRunResult]],
    ) -> tuple[bool, str]:
        async with self._lock:
            if self.is_running():
                return False, "⏳ Todo queue is already running."

            items = parse_todo_file(self.config.todo.file)
            if not items:
                return False, "📋 No todo items found."

            prepared, issues = prepare_todo_items(items, self.config)
            if issues:
                lines = ["❌ Todo validation failed:"]
                for issue in issues[:8]:
                    lines.append(
                        f"- P{issue.item.priority} `{issue.item.cli}` `{issue.item.project}`: {issue.message}"
                    )
                if len(issues) > 8:
                    lines.append(f"- ...and {len(issues) - 8} more")
                return False, "\n".join(lines)

            self._reset_runtime(prepared)
            self._run_task = asyncio.create_task(self._run_queue(channel, prepared, runner))
            return True, f"📋 Starting todo queue: {len(prepared)} task{'s' if len(prepared) != 1 else ''}"

    async def cancel(self) -> bool:
        async with self._lock:
            if not self.is_running():
                return False
            self._stop_requested = True
            active = list(self._active.values())

        for item in active:
            await self.task_manager.cancel(item.project_name)
        return True

    async def wait_closed(self) -> None:
        task = self._run_task
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)

    def _reset_runtime(self, prepared: list[PreparedTodoItem]) -> None:
        self._stop_requested = False
        self._pending = list(prepared)
        self._active = {}
        self._active_projects = set()
        self._task_lookup = {}
        self._started_at = time.monotonic()
        self._current_priority = None
        self._total = len(prepared)
        self._completed = 0
        self._failed = 0
        self._cancelled = 0

    async def _run_queue(
        self,
        channel: discord.abc.Messageable,
        prepared: list[PreparedTodoItem],
        runner: Callable[[PreparedTodoItem, discord.abc.Messageable], Awaitable[TodoRunResult]],
    ) -> None:
        try:
            for priority in sorted({item.item.priority for item in prepared}):
                if self._stop_requested:
                    break

                self._current_priority = priority
                bucket = [item for item in self._pending if item.item.priority == priority]
                await channel.send(
                    f"▶️ Priority {priority} - {len(bucket)} task{'s' if len(bucket) != 1 else ''}"
                )

                await self._run_priority_bucket(channel, runner, bucket)

            await channel.send(self._final_summary())
        except Exception as exc:
            logger.exception("Todo queue failed: %s", exc)
            await channel.send(f"❌ Todo queue crashed: {exc}")
        finally:
            self._pending = []
            self._active = {}
            self._active_projects = set()
            self._task_lookup = {}
            self._current_priority = None
            self._started_at = None
            self._run_task = None
            self._stop_requested = False

    async def _run_priority_bucket(
        self,
        channel: discord.abc.Messageable,
        runner: Callable[[PreparedTodoItem, discord.abc.Messageable], Awaitable[TodoRunResult]],
        bucket: list[PreparedTodoItem],
    ) -> None:
        while bucket or self._active:
            if self._stop_requested and not self._active:
                break

            dispatched = False
            if not self._stop_requested:
                for item in list(bucket):
                    if item.cli_key in self._active:
                        continue
                    if item.project_name in self._active_projects:
                        continue
                    if self.task_manager.is_cli_busy(item.cli_key):
                        continue
                    if self.task_manager.is_busy(item.project_name):
                        continue

                    bucket.remove(item)
                    if item in self._pending:
                        self._pending.remove(item)
                    self._active[item.cli_key] = item
                    self._active_projects.add(item.project_name)
                    await channel.send(
                        f"[{item.item.cli}] 🚀 {item.item.task}"
                    )
                    task = asyncio.create_task(runner(item, channel))
                    self._task_lookup[task] = item.cli_key
                    dispatched = True

            if not self._task_lookup:
                await asyncio.sleep(1)
                continue

            timeout = 0.5 if not dispatched else None
            done, _ = await asyncio.wait(
                list(self._task_lookup.keys()),
                timeout=timeout,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                cli_key = self._task_lookup.pop(task, "")
                active_item = None
                if cli_key:
                    active_item = self._active.pop(cli_key, None)
                    if active_item is not None:
                        self._active_projects.discard(active_item.project_name)
                try:
                    result = await task
                except Exception as exc:
                    logger.exception("Todo item failed unexpectedly: %s", exc)
                    if active_item is None:
                        continue
                    result = TodoRunResult(
                        item=active_item,
                        status="failed",
                        duration=0,
                        summary=f"Unexpected error: {exc}",
                    )

                await self._finalize_result(channel, result)

    async def _finalize_result(
        self,
        channel: discord.abc.Messageable,
        result: TodoRunResult,
    ) -> None:
        self._record_result(result)
        remove_todo_item(self.config.todo.file, result.item.item)
        archive_todo_result(self.config.todo.done_file, result)
        await channel.send(self._format_item_result(result))

    def _record_result(self, result: TodoRunResult) -> None:
        if result.status == "success":
            self._completed += 1
        elif result.status == "cancelled":
            self._cancelled += 1
        else:
            self._failed += 1

    def _format_item_result(self, result: TodoRunResult) -> str:
        prefix = f"[{result.item.item.cli}]"
        if result.status == "success":
            return f"{prefix} ✅ Done ({result.duration:.0f}s)"
        if result.status == "cancelled":
            return f"{prefix} 🛑 Cancelled ({result.duration:.0f}s)"
        if result.returncode is None:
            return f"{prefix} ❌ Failed ({result.duration:.0f}s)"
        return f"{prefix} ❌ Failed ({result.duration:.0f}s, exit {result.returncode})"

    def _final_summary(self) -> str:
        finished = self._completed + self._failed + self._cancelled
        if self._stop_requested and finished < self._total:
            return (
                f"🛑 Todo queue stopped. Completed: {self._completed}, "
                f"failed: {self._failed}, cancelled: {self._cancelled}, "
                f"remaining: {self._total - finished}."
            )
        return (
            f"📋 Todo queue complete. "
            f"{self._completed}/{self._total} succeeded, "
            f"{self._failed} failed, {self._cancelled} cancelled."
        )
