"""Task lifecycle manager — single task at a time."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import discord

from devbot.executor.runner import run_subprocess, kill_process
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
        self._current: TaskInfo | None = None
        self._process: asyncio.subprocess.Process | None = None

    def is_busy(self) -> bool:
        return self._current is not None

    def current_info(self) -> TaskInfo | None:
        return self._current

    async def execute(
        self,
        adapter: "BaseCLIAdapter",
        task: str,
        project_path: str,
        project_name: str,
        channel: discord.abc.Messageable,
    ) -> TaskResult:
        if self.is_busy():
            raise RuntimeError("A task is already running.")

        cmd = adapter.build_command(task, project_path)
        info = TaskInfo(cli_name=adapter.name, project=project_name, task=task)
        self._current = info

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
                on_process=lambda p: setattr(self, "_process", p),
            )
        except Exception as exc:
            logger.exception("Task raised an exception: %s", exc)
            returncode = -1
            await streamer.on_output(f"Internal error: {exc}")
        finally:
            duration = info.elapsed()
            self._current = None
            self._process = None

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

    async def cancel(self) -> bool:
        if not self.is_busy() or self._process is None:
            return False
        await kill_process(self._process)
        return True
