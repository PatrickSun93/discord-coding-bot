"""Task lifecycle manager — per-project concurrent tasks."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import discord

from devbot.executor.runner import kill_process, run_subprocess
from devbot.executor.stream import DiscordStreamer
from devbot.executor.stream_parser import make_json_output_handler
from devbot.history import record_task

if TYPE_CHECKING:
    from devbot.config.settings import Config
    from devbot.executor.adapters.base import BaseCLIAdapter

logger = logging.getLogger(__name__)


@dataclass
class TaskInfo:
    cli_name: str
    project: str
    task: str
    workflow: str = ""
    run_id: str = ""
    log_path: str = ""
    started_at: float = field(default_factory=time.monotonic)
    process: Any = None

    def elapsed(self) -> float:
        return time.monotonic() - self.started_at


@dataclass
class TaskResult:
    returncode: int
    transcript: str
    duration: float


class TaskManager:
    def __init__(self, config: "Config"):
        self.config = config
        self._tasks: dict[str, TaskInfo] = {}
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    def is_busy(self, project: str | None = None) -> bool:
        """Return True if a task is running. If project given, checks only that project."""
        if project is not None:
            return project in self._tasks
        return bool(self._tasks)

    def current_info(self, project: str | None = None) -> TaskInfo | None:
        """Return TaskInfo for a specific project, or the first running task if None."""
        if project is not None:
            return self._tasks.get(project)
        return next(iter(self._tasks.values()), None)

    def is_cli_busy(self, cli_name: str) -> bool:
        """Return True if any running task is using the given CLI."""
        return self.current_cli_info(cli_name) is not None

    def current_cli_info(self, cli_name: str) -> TaskInfo | None:
        """Return the first running TaskInfo for a given CLI, if any."""
        for info in self._tasks.values():
            if info.cli_name == cli_name:
                return info
        return None

    def all_tasks(self) -> dict[str, TaskInfo]:
        """Return a snapshot of all currently running tasks keyed by project name."""
        return dict(self._tasks)

    async def execute(
        self,
        adapter: "BaseCLIAdapter",
        task: str,
        project_path: str,
        project_name: str,
        channel: discord.abc.Messageable,
        workflow: str = "",
        run_id: str = "",
        log_path: str = "",
    ) -> TaskResult:
        if self.is_busy(project_name):
            raise RuntimeError(f"A task is already running for project '{project_name}'.")

        cmd = adapter.build_command(task, project_path)
        info = TaskInfo(
            cli_name=adapter.name,
            project=project_name,
            task=task,
            workflow=workflow,
            run_id=run_id,
            log_path=log_path,
        )
        self._tasks[project_name] = info

        streamer = DiscordStreamer(
            channel=channel,
            batch_threshold=self.config.reporter.stream_threshold,
            batch_interval=self.config.reporter.batch_interval,
            max_lines=200,
        )

        # Wrap the streamer's on_output with the JSON parser so NDJSON events
        # from CLI stream-json mode are decoded to plain text before display.
        json_handler = make_json_output_handler(streamer.on_output)

        logger.info("Starting task: %s in %s via %s", task[:60], project_path, adapter.name)
        logger.debug("Command: %s", cmd)

        cli_cfg = getattr(self.config.cli, adapter.name, None)
        timeout = cli_cfg.timeout if cli_cfg else 600

        try:
            returncode = await run_subprocess(
                cmd=cmd,
                cwd=project_path,
                on_output=json_handler,
                timeout=timeout,
                on_process=lambda p: self._processes.__setitem__(project_name, p),
            )
        except Exception as exc:
            logger.exception("Task raised an exception: %s", exc)
            returncode = -1
            await streamer.on_output(f"Internal error: {exc}")
        finally:
            duration = info.elapsed()
            self._tasks.pop(project_name, None)
            self._processes.pop(project_name, None)

        try:
            record_task(
                cli_name=adapter.name,
                project=project_name,
                task=task,
                returncode=returncode,
                duration=duration,
            )
        except Exception as exc:
            logger.warning("Failed to record task history: %s", exc)

        await streamer.send_result(
            returncode=returncode,
            cli_name=adapter.name,
            project=project_name,
            task=task,
            duration=duration,
        )
        return TaskResult(
            returncode=returncode,
            transcript="\n".join(streamer.all_output),
            duration=duration,
        )

    async def cancel(self, project: str | None = None) -> bool:
        """Cancel a specific project's task, or all running tasks if project is None."""
        if project is not None:
            proc = self._processes.get(project)
            if proc is None:
                return False
            await kill_process(proc)
            return True

        if not self._processes:
            return False

        for proc in list(self._processes.values()):
            await kill_process(proc)
        return True
