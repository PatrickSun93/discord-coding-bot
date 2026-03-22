"""Discord bot client and on_message handler."""

from __future__ import annotations

import asyncio
import logging
import shlex
from pathlib import Path
from typing import TYPE_CHECKING

import discord

from devbot.bot.commands import register_commands
from devbot.bot.formatter import (
    format_project_list,
    format_todo_list,
    format_todo_status,
)
from devbot.context.files import (
    build_file_bundle,
    resolve_project_files,
    select_analysis_files,
)
from devbot.context.loader import load_project_context
from devbot.context.project import resolve_project
from devbot.executor.adapters.factory import build_adapter
from devbot.executor.auto_restart import (
    AutoRestartResult,
    capture_project_snapshot,
    detect_restart_relevant_changes,
    resolve_auto_restart_plan,
)
from devbot.executor.manager import TaskManager
from devbot.executor.shell import is_command_blocked, run_shell
from devbot.executor.shell.platform import detect_platform
from devbot.healthcheck import HealthReport, format_health_report
from devbot.llm.router import LLMRouter
from devbot.todo import (
    PreparedTodoItem,
    TodoExecutor,
    TodoItem,
    TodoRunResult,
    add_todo_item,
    display_todo_cli,
    parse_todo_file,
    prepare_todo_item,
)
from devbot.workflow.models import ActiveWorkflowStatus
from devbot.workflow.pipeline import FeatureDeliveryPipeline
from devbot.workflow.prompts import build_analysis_prompt, build_cli_task_prompt
from devbot.workflow.registry import select_cli_for_role
from devbot.workflow.store import (
    append_workflow_event,
    read_workflow_events,
    set_workflow_status,
    start_workflow_run,
    write_artifact,
)

if TYPE_CHECKING:
    from devbot.config.settings import Config, ProjectConfig

logger = logging.getLogger(__name__)

# Reaction emojis used for status feedback
_REACT_THINKING = "👀"
_REACT_OK = "✅"
_REACT_ERROR = "❌"
_REACT_QUESTION = "🤔"


async def _react(message: discord.Message, emoji: str) -> None:
    """Add a reaction, silently ignoring permission errors."""
    try:
        await message.add_reaction(emoji)
    except discord.HTTPException:
        pass


async def _clear_reaction(message: discord.Message, emoji: str, me: discord.ClientUser) -> None:
    """Remove bot's own reaction, silently ignoring errors."""
    try:
        await message.remove_reaction(emoji, me)
    except discord.HTTPException:
        pass


def _clip(text: str, limit: int = 1800) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _split_chunks(text: str, chunk_size: int = 1800) -> list[str]:
    """Split text into chunks at line boundaries, each <= chunk_size chars."""
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines(keepends=True):
        if current_len + len(line) > chunk_size and current:
            chunks.append("".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line)
    if current:
        chunks.append("".join(current))
    return chunks


def _format_file_list(files: list[str]) -> str:
    if not files:
        return "(none)"
    return ", ".join(files)


class DevBotClient(discord.Client):
    def __init__(self, config: "Config"):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

        self.config = config
        self.tree = discord.app_commands.CommandTree(self)
        self.task_manager = TaskManager(config)
        self.todo_executor = TodoExecutor(config, self.task_manager)
        self.llm_router = LLMRouter(config)
        self._restarting_projects: set[str] = set()
        self._active_pipelines: set[str] = set()
        self._active_pipeline_runs: dict[str, object] = {}
        self._cancelled_pipelines: set[str] = set()
        self._startup_health_report: HealthReport | None = None
        self._startup_health_announced = False
        self._platform = detect_platform(
            preferred=config.shell.default,
            wsl_distro=config.shell.wsl_distro,
        )

        register_commands(self)

    async def setup_hook(self) -> None:
        await self.tree.sync()
        logger.info("Slash commands synced.")

    async def on_ready(self) -> None:
        logger.info("DevBot ready — logged in as %s (id=%s)", self.user, self.user.id)
        if self._startup_health_report is not None and not self._startup_health_announced:
            asyncio.create_task(self._announce_startup_health())
        if self.config.todo.auto_start:
            asyncio.create_task(self._auto_start_todo())

    async def close(self) -> None:
        self.request_pipeline_cancel()
        await self.task_manager.cancel()
        await self.todo_executor.cancel()
        await self.todo_executor.wait_closed()
        await super().close()

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        if message.author.id != self.config.discord.owner_id:
            return

        if (
            self.config.discord.channel_id
            and message.channel.id != self.config.discord.channel_id
        ):
            return

        if message.content.startswith("/"):
            return

        content = message.content.strip()
        if not content:
            return

        await _react(message, _REACT_THINKING)
        if content.startswith("!todo"):
            asyncio.ensure_future(self._handle_todo_command(message, content))
            return
        if content.startswith("!project"):
            asyncio.ensure_future(self._handle_project_command(message, content))
            return
        asyncio.ensure_future(self._handle_message(message, content))

    def _project_profile(self, project_name: str, project_path: str) -> "ProjectConfig":
        from devbot.config.settings import ProjectConfig

        return self.config.projects.get(project_name, ProjectConfig(path=Path(project_path)))

    def _is_project_pipeline_active(self, project_name: str) -> bool:
        return project_name in self._active_pipelines

    def active_pipeline_statuses(self) -> list[ActiveWorkflowStatus]:
        statuses: list[ActiveWorkflowStatus] = []
        for project_name, run in self._active_pipeline_runs.items():
            events = read_workflow_events(run)
            latest = events[-1] if events else {}
            statuses.append(
                ActiveWorkflowStatus(
                    project_name=project_name,
                    workflow=run.workflow,
                    run_id=run.run_id,
                    log_path=run.run_dir / "timeline.md",
                    stage=str(latest.get("stage", "")),
                    status=str(latest.get("status", "")),
                    message=str(latest.get("message", "")),
                )
            )
        statuses.sort(key=lambda item: item.project_name.lower())
        return statuses

    def request_pipeline_cancel(self, project_name: str | None = None) -> bool:
        if project_name is not None:
            if project_name not in self._active_pipelines:
                return False
            self._cancelled_pipelines.add(project_name)
            return True

        if not self._active_pipelines:
            return False
        self._cancelled_pipelines.update(self._active_pipelines)
        return True

    def _is_pipeline_cancelled(self, project_name: str) -> bool:
        return project_name in self._cancelled_pipelines

    def _project_busy_message(self, project_name: str) -> str | None:
        if project_name in self._restarting_projects:
            return f"⏳ `{project_name}` is restarting. Wait for it to finish and try again."
        if self._is_project_pipeline_active(project_name):
            return (
                f"⏳ A feature pipeline is already running for `{project_name}`. "
                f"Use `/cancel {project_name}` to stop it."
            )
        if self.task_manager.is_busy(project_name):
            return (
                f"⏳ A task is already running for `{project_name}`. "
                f"Use `/cancel {project_name}` to stop it."
            )
        return None

    async def _announce_startup_health(self) -> None:
        report = self._startup_health_report
        if report is None or self._startup_health_announced:
            return

        self._startup_health_announced = True
        message = format_health_report(report, title="Startup Healthcheck")
        channel_id = self.config.discord.channel_id
        if not channel_id:
            logger.info("Startup healthcheck:\n%s", format_health_report(report, markdown=False))
            return

        channel = self.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(channel_id)
            except discord.HTTPException as exc:
                logger.warning("Startup healthcheck failed to fetch channel %s: %s", channel_id, exc)
                logger.info("Startup healthcheck:\n%s", format_health_report(report, markdown=False))
                return

        try:
            await channel.send(message)
        except discord.HTTPException as exc:
            logger.warning("Failed to send startup healthcheck: %s", exc)
            logger.info("Startup healthcheck:\n%s", format_health_report(report, markdown=False))

    def _resolve_registered_project(self, project_arg: str) -> tuple[str, str] | None:
        wanted = project_arg.strip().lower()
        for project_name, project_cfg in self.config.projects.items():
            if project_name.lower() == wanted:
                return str(project_cfg.path), project_name
        return None

    def _restart_project_resolution_error(self, project_arg: str = "") -> str:
        detail = f"Unknown project `{project_arg}`. " if project_arg.strip() else ""
        if not self.config.projects:
            return f"❌ {detail}No projects are registered. Use `/project add <name> <path>` first."
        return (
            f"❌ {detail}Restart requires a registered project name because restart commands live in the project config.\n"
            + format_project_list(self.config.projects)
        )

    async def _resolve_project(self, message: discord.Message, project_arg: str) -> tuple[str, str] | None:
        if not project_arg:
            if len(self.config.projects) == 1:
                project_arg = next(iter(self.config.projects))
            else:
                await _clear_reaction(message, _REACT_THINKING, self.user)
                await _react(message, _REACT_QUESTION)
                await message.reply(
                    "🤔 Which project? Mention a project name or path.\n"
                    + format_project_list(self.config.projects)
                )
                return None

        try:
            return resolve_project(project_arg, self.config)
        except ValueError as exc:
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await _react(message, _REACT_ERROR)
            await message.reply(f"❌ {exc}")
            return None

    async def _auto_start_todo(self) -> None:
        channel_id = self.config.discord.channel_id
        if not channel_id:
            logger.info("Todo auto-start skipped: discord.channel_id is not configured.")
            return

        channel = self.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(channel_id)
            except discord.HTTPException as exc:
                logger.warning("Todo auto-start failed to fetch channel %s: %s", channel_id, exc)
                return

        started, reply = await self.todo_executor.start(channel, self._run_todo_item)
        if started:
            await channel.send(reply)
        else:
            logger.info("Todo auto-start skipped: %s", reply)

    def _todo_help_text(self) -> str:
        return "\n".join([
            "**Todo Commands**",
            "`!todo add <cli> <project> <task>`",
            "`!todo add <cli> <project> <task> --priority 1`",
            "`!todo list`",
            "`!todo run`",
            "`!todo status`",
            "`!todo cancel`",
        ])

    def _project_help_text(self) -> str:
        return "\n".join([
            "**Project Commands**",
            "`!project restart <name>`",
        ])

    def _parse_todo_add_args(self, args: list[str]) -> tuple[str, str, str, int]:
        priority = 3
        cleaned: list[str] = []
        index = 0
        while index < len(args):
            token = args[index]
            if token == "--priority":
                if index + 1 >= len(args):
                    raise ValueError("Missing value after `--priority`.")
                try:
                    priority = int(args[index + 1])
                except ValueError as exc:
                    raise ValueError("Priority must be an integer.") from exc
                index += 2
                continue
            cleaned.append(token)
            index += 1

        if len(cleaned) < 3:
            raise ValueError("Usage: `!todo add <cli> <project> <task> [--priority N]`")

        cli_name = cleaned[0]
        project = cleaned[1]
        task = " ".join(cleaned[2:]).strip()
        if not task:
            raise ValueError("Todo task text cannot be empty.")
        return cli_name, project, task, priority

    def _prepare_cli_execution(
        self,
        *,
        cli_key: str,
        task: str,
        project_path: str,
        project_name: str,
        workflow: str,
        role: str,
        source: str,
        files: list[str] | None = None,
        metadata: dict | None = None,
    ):
        cli_cfg = getattr(self.config.cli, cli_key, None)
        if cli_cfg is None:
            raise RuntimeError(f"Unknown CLI: `{cli_key}`")
        if not cli_cfg.enabled:
            raise RuntimeError(f"CLI `{cli_key}` is disabled in config.")

        adapter = build_adapter(cli_key, self.config)
        if not adapter.is_available():
            raise RuntimeError(
                f"`{cli_cfg.command}` not found on PATH. Install it or check your config."
            )

        project_cfg = self._project_profile(project_name, project_path)
        run = start_workflow_run(
            project_path=project_path,
            project_name=project_name,
            workflow=workflow,
            role=role,
            goal=task,
            metadata=metadata or {"cli": cli_key, "source": source, "files": files or []},
        )
        project_context = load_project_context(project_path, self.config, project_name)
        task_prompt = build_cli_task_prompt(
            task=task,
            project_name=project_name,
            project_cfg=project_cfg,
            project_context=project_context,
            files=files or [],
            run=run,
        )

        write_artifact(run, "request.md", task)
        if project_context:
            write_artifact(run, "project-context.md", project_context)
        write_artifact(run, "task-prompt.md", task_prompt)
        append_workflow_event(
            run,
            stage=role,
            status="queued",
            message=f"Prepared {source} task for `{cli_key}`.",
            details={"cli": cli_key, "source": source, "files": files or []},
        )
        return adapter, run, task_prompt

    def _summarize_transcript(self, transcript: str) -> str:
        if not transcript:
            return ""
        for line in reversed(transcript.splitlines()):
            stripped = line.strip()
            if stripped:
                return _clip(stripped, 220)
        return ""

    def _format_changed_paths(self, changed_paths: list[str]) -> str:
        if not changed_paths:
            return "changes detected"
        preview = ", ".join(f"`{path}`" for path in changed_paths[:4])
        if len(changed_paths) > 4:
            preview += f" and {len(changed_paths) - 4} more"
        return preview

    async def _maybe_auto_restart_project(
        self,
        project_name: str,
        project_path: str,
        snapshot,
        channel: discord.abc.Messageable,
    ) -> AutoRestartResult:
        if snapshot is None:
            return AutoRestartResult()

        project_cfg = self._project_profile(project_name, project_path)
        after = capture_project_snapshot(project_path)
        changed_paths = detect_restart_relevant_changes(snapshot, after)
        if not changed_paths:
            return AutoRestartResult(changed_paths=[])

        run = start_workflow_run(
            project_path=project_path,
            project_name=project_name,
            workflow="restart",
            role="release",
            goal=f"auto restart {project_name}",
            metadata={"source": "auto_restart", "changed_paths": changed_paths},
        )
        write_artifact(
            run,
            "request.md",
            "\n".join(
                [
                    f"Project: {project_name}",
                    "Mode: auto_restart",
                    "Changed paths:",
                    *changed_paths,
                    "",
                ]
            ),
        )
        append_workflow_event(
            run,
            stage="restart",
            status="started",
            message="Auto-restart evaluation started.",
            details={"changed_paths": changed_paths},
        )

        plan, reason = resolve_auto_restart_plan(self.config, project_cfg, project_name)
        if plan is None:
            message = reason or f"Auto-restart is not configured for `{project_name}`."
            append_workflow_event(run, stage="restart", status="failed", message=message)
            set_workflow_status(run, status="failed", summary=message)
            await channel.send(f"⚠️ {message}")
            return AutoRestartResult(
                attempted=True,
                restarted=False,
                message=message,
                changed_paths=changed_paths,
            )

        blocked, block_reason = is_command_blocked(plan.command)
        if blocked:
            message = (
                f"Auto-restart blocked for `{project_name}` because the restart command matched "
                f"the shell safety blocklist: `{block_reason}`."
            )
            write_artifact(run, "restart-command.txt", plan.command + "\n")
            append_workflow_event(
                run,
                stage="restart",
                status="failed",
                message=message,
                details={"block_reason": block_reason},
            )
            set_workflow_status(run, status="failed", summary=message)
            await channel.send(f"⚠️ {message}")
            return AutoRestartResult(
                attempted=True,
                restarted=False,
                message=message,
                changed_paths=changed_paths,
            )

        change_text = self._format_changed_paths(changed_paths)
        await channel.send(
            f"🔁 Auto-restarting `{project_name}` via {plan.source} because {change_text}.\n"
            f"Run: `{run.run_id}`\n"
            f"Logs: `{run.run_dir / 'timeline.md'}`"
        )
        write_artifact(run, "restart-command.txt", plan.command + "\n")
        append_workflow_event(
            run,
            stage="restart",
            status="started",
            message="Executing auto-restart command.",
            details={"command": plan.command, "shell": plan.shell},
        )

        self._restarting_projects.add(project_name)
        try:
            shell_result = await run_shell(
                command=plan.command,
                shell=plan.shell,
                working_dir=project_path,
                timeout=self.config.shell.timeout,
                platform_info=self._platform,
            )
        finally:
            self._restarting_projects.discard(project_name)
        write_artifact(run, "restart-output.txt", shell_result.output or "(no output)")

        if shell_result.returncode == 0:
            message = (
                f"Auto-restarted `{project_name}` in `{shell_result.shell}` after "
                f"{change_text}."
            )
            append_workflow_event(
                run,
                stage="restart",
                status="completed",
                message=message,
                details={"shell": shell_result.shell, "returncode": shell_result.returncode},
            )
            set_workflow_status(
                run,
                status="succeeded",
                summary=message,
                extra={"shell": shell_result.shell, "returncode": shell_result.returncode},
            )
            await channel.send(f"✅ {message}")
            return AutoRestartResult(
                attempted=True,
                restarted=True,
                message=message,
                output=shell_result.output,
                changed_paths=changed_paths,
            )

        failure_output = _clip(shell_result.output or "(no output)", 600)
        message = (
            f"Auto-restart failed for `{project_name}` in `{shell_result.shell}` "
            f"(exit `{shell_result.returncode}`)."
        )
        append_workflow_event(
            run,
            stage="restart",
            status="failed",
            message=message,
            details={"shell": shell_result.shell, "returncode": shell_result.returncode},
        )
        set_workflow_status(
            run,
            status="failed",
            summary=message,
            extra={"shell": shell_result.shell, "returncode": shell_result.returncode},
        )
        await channel.send(f"❌ {message}\n```\n{failure_output}\n```")
        return AutoRestartResult(
            attempted=True,
            restarted=False,
            message=message,
            output=shell_result.output,
            changed_paths=changed_paths,
        )

    async def _restart_project_now(
        self,
        project_name: str,
        project_path: str,
    ) -> tuple[bool, str]:
        if project_name in self._restarting_projects:
            return False, f"⏳ `{project_name}` is already restarting."

        if self._is_project_pipeline_active(project_name):
            return False, (
                f"⏳ A feature pipeline is already running for `{project_name}`. "
                f"Use `/cancel {project_name}` to stop it first."
            )
        if self.task_manager.is_busy(project_name):
            return False, (
                f"⏳ A task is already running for `{project_name}`. "
                f"Use `/cancel {project_name}` to stop it first."
            )

        run = start_workflow_run(
            project_path=project_path,
            project_name=project_name,
            workflow="restart",
            role="release",
            goal=f"manual restart {project_name}",
            metadata={"source": "manual_restart"},
        )
        append_workflow_event(
            run,
            stage="restart",
            status="started",
            message="Manual restart requested.",
        )
        project_cfg = self._project_profile(project_name, project_path)
        plan, reason = resolve_auto_restart_plan(
            self.config,
            project_cfg,
            project_name,
            require_enabled=False,
        )
        if plan is None:
            message = reason or (
                f"No restart command is configured for `{project_name}`. "
                "Set `commands.restart` or `restart_service` in the project config."
            )
            append_workflow_event(run, stage="restart", status="failed", message=message)
            set_workflow_status(run, status="failed", summary=message)
            return False, (
                f"❌ {message}\n"
                f"Run: `{run.run_id}`\n"
                f"Logs: `{run.run_dir / 'timeline.md'}`"
            )

        blocked, block_reason = is_command_blocked(plan.command)
        if blocked:
            message = (
                f"Restart command for `{project_name}` is blocked by the shell safety "
                f"blocklist: `{block_reason}`."
            )
            write_artifact(run, "restart-command.txt", plan.command + "\n")
            append_workflow_event(
                run,
                stage="restart",
                status="failed",
                message=message,
                details={"block_reason": block_reason},
            )
            set_workflow_status(run, status="failed", summary=message)
            return False, (
                f"❌ {message}\n"
                f"Run: `{run.run_id}`\n"
                f"Logs: `{run.run_dir / 'timeline.md'}`"
            )

        write_artifact(run, "restart-command.txt", plan.command + "\n")
        append_workflow_event(
            run,
            stage="restart",
            status="started",
            message="Executing manual restart command.",
            details={"command": plan.command, "shell": plan.shell},
        )
        self._restarting_projects.add(project_name)
        try:
            shell_result = await run_shell(
                command=plan.command,
                shell=plan.shell,
                working_dir=project_path,
                timeout=self.config.shell.timeout,
                platform_info=self._platform,
            )
        finally:
            self._restarting_projects.discard(project_name)
        write_artifact(run, "restart-output.txt", shell_result.output or "(no output)")

        if shell_result.returncode == 0:
            message = f"Restarted `{project_name}` via {plan.source} in `{shell_result.shell}`."
            append_workflow_event(
                run,
                stage="restart",
                status="completed",
                message=message,
                details={"shell": shell_result.shell, "returncode": shell_result.returncode},
            )
            set_workflow_status(
                run,
                status="succeeded",
                summary=message,
                extra={"shell": shell_result.shell, "returncode": shell_result.returncode},
            )
            lines = [
                f"✅ {message}",
                f"Run: `{run.run_id}`",
                f"Logs: `{run.run_dir / 'timeline.md'}`",
            ]
            if shell_result.output:
                lines.append(f"```\n{_clip(shell_result.output, 900)}\n```")
            return True, "\n".join(lines)

        output = _clip(shell_result.output or "(no output)", 900)
        message = (
            f"Restart failed for `{project_name}` in `{shell_result.shell}` "
            f"(exit `{shell_result.returncode}`)."
        )
        append_workflow_event(
            run,
            stage="restart",
            status="failed",
            message=message,
            details={"shell": shell_result.shell, "returncode": shell_result.returncode},
        )
        set_workflow_status(
            run,
            status="failed",
            summary=message,
            extra={"shell": shell_result.shell, "returncode": shell_result.returncode},
        )
        return False, (
            f"❌ {message}\n"
            f"Run: `{run.run_id}`\n"
            f"Logs: `{run.run_dir / 'timeline.md'}`\n"
            f"```\n{output}\n```"
        )

    async def _run_feature_pipeline(
        self,
        *,
        project_name: str,
        project_path: str,
        task: str,
        channel: discord.abc.Messageable,
        source: str,
    ):
        project_cfg = self._project_profile(project_name, project_path)
        pipeline = FeatureDeliveryPipeline(
            config=self.config,
            task_manager=self.task_manager,
            channel=channel,
            platform_info=self._platform,
            project_name=project_name,
            project_path=project_path,
            project_cfg=project_cfg,
            task=task,
            source=source,
            cancel_requested=lambda: self._is_pipeline_cancelled(project_name),
        )
        self._active_pipelines.add(project_name)
        self._active_pipeline_runs[project_name] = pipeline.run
        self._cancelled_pipelines.discard(project_name)
        try:
            return await pipeline.run_pipeline()
        finally:
            self._active_pipelines.discard(project_name)
            self._active_pipeline_runs.pop(project_name, None)
            self._cancelled_pipelines.discard(project_name)

    async def _run_todo_item(
        self,
        item: PreparedTodoItem,
        channel: discord.abc.Messageable,
    ) -> TodoRunResult:
        if item.mode == "pipeline":
            pipeline_result = await self._run_feature_pipeline(
                project_name=item.project_name,
                project_path=item.project_path,
                task=item.item.task,
                channel=channel,
                source="todo_pipeline",
            )
            status = "success" if pipeline_result.success else "failed"
            if status == "failed" and self.todo_executor.stop_requested:
                status = "cancelled"
            return TodoRunResult(
                item=item,
                status=status,
                duration=pipeline_result.duration,
                summary=pipeline_result.summary,
                returncode=0 if pipeline_result.success else 1,
            )

        task_text = item.item.task
        workflow = "todo"
        try:
            adapter, run, task_prompt = self._prepare_cli_execution(
                cli_key=item.cli_key,
                task=task_text,
                project_path=item.project_path,
                project_name=item.project_name,
                workflow=workflow,
                role="coder",
                source="todo",
                metadata={
                    "cli": item.cli_key,
                    "source": "todo",
                    "queue_cli": item.item.cli,
                    "mode": item.mode,
                },
            )
        except RuntimeError as exc:
            return TodoRunResult(
                item=item,
                status="failed",
                duration=0,
                summary=str(exc),
            )

        project_cfg = self._project_profile(item.project_name, item.project_path)
        snapshot = capture_project_snapshot(item.project_path) if project_cfg.auto_restart else None
        append_workflow_event(
            run,
            stage="coder",
            status="started",
            message=f"Todo item started on `{item.cli_key}`.",
            details={"source": "todo", "queue_cli": item.item.cli},
        )
        result = await self.task_manager.execute(
            adapter=adapter,
            task=task_prompt,
            project_path=item.project_path,
            project_name=item.project_name,
            channel=channel,
            workflow=workflow,
            run_id=run.run_id,
            log_path=str(run.run_dir / "timeline.md"),
        )

        write_artifact(run, "transcript.md", result.transcript or "(no output)")
        restart_result = AutoRestartResult()
        if result.returncode == 0:
            restart_result = await self._maybe_auto_restart_project(
                project_name=item.project_name,
                project_path=item.project_path,
                snapshot=snapshot,
                channel=channel,
            )

        status = "success" if result.returncode == 0 else "failed"
        if status == "success" and restart_result.failed:
            status = "failed"
        if status == "failed" and self.todo_executor.stop_requested:
            status = "cancelled"
        summary_parts = [self._summarize_transcript(result.transcript)]
        if restart_result.attempted:
            summary_parts.append(restart_result.message)
        append_workflow_event(
            run,
            stage="coder",
            status="completed" if status == "success" else status,
            message=f"Todo item finished with status `{status}`.",
            details={"returncode": result.returncode},
        )
        set_workflow_status(
            run,
            status="succeeded" if status == "success" else status,
            summary=" | ".join(part for part in summary_parts if part),
            extra={"returncode": result.returncode},
        )
        return TodoRunResult(
            item=item,
            status=status,
            duration=result.duration,
            summary=" | ".join(part for part in summary_parts if part),
            returncode=result.returncode,
        )

    async def _handle_todo_command(self, message: discord.Message, content: str) -> None:
        try:
            tokens = shlex.split(content)
        except ValueError as exc:
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await _react(message, _REACT_ERROR)
            await message.reply(f"❌ Invalid todo command: {exc}")
            return

        emoji = _REACT_OK
        reply = self._todo_help_text()
        try:
            if len(tokens) == 1:
                reply = self._todo_help_text()
                emoji = _REACT_QUESTION
            else:
                subcommand = tokens[1].lower()
                if subcommand == "add":
                    reply, emoji = await self._todo_add_command(tokens[2:])
                elif subcommand == "list":
                    reply = format_todo_list(parse_todo_file(self.config.todo.file))
                elif subcommand == "run":
                    started, reply = await self.todo_executor.start(message.channel, self._run_todo_item)
                    emoji = _REACT_OK if started else (_REACT_ERROR if reply.startswith("❌") else _REACT_QUESTION)
                elif subcommand == "status":
                    reply = format_todo_status(self.todo_executor.status())
                elif subcommand == "cancel":
                    cancelled = await self.todo_executor.cancel()
                    pipeline_cancelled = self.request_pipeline_cancel()
                    cancelled = cancelled or pipeline_cancelled
                    reply = "🛑 Todo queue cancellation requested." if cancelled else "📋 No todo queue is running."
                    emoji = _REACT_OK if cancelled else _REACT_QUESTION
                else:
                    reply = self._todo_help_text()
                    emoji = _REACT_QUESTION
        except Exception as exc:
            logger.exception("Todo command failed: %s", exc)
            reply = f"❌ Todo command failed: {exc}"
            emoji = _REACT_ERROR

        await _clear_reaction(message, _REACT_THINKING, self.user)
        await _react(message, emoji)
        await message.reply(reply)

    async def _handle_project_command(self, message: discord.Message, content: str) -> None:
        try:
            tokens = shlex.split(content)
        except ValueError as exc:
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await _react(message, _REACT_ERROR)
            await message.reply(f"❌ Invalid project command: {exc}")
            return

        emoji = _REACT_OK
        reply = self._project_help_text()

        if len(tokens) == 1:
            emoji = _REACT_QUESTION
        else:
            subcommand = tokens[1].lower()
            if subcommand == "restart":
                project_arg = " ".join(tokens[2:]).strip()
                if not project_arg:
                    reply = "❌ Usage: `!project restart <name>`"
                    emoji = _REACT_ERROR
                else:
                    resolved = self._resolve_registered_project(project_arg)
                    if resolved is None:
                        reply = self._restart_project_resolution_error(project_arg)
                        emoji = _REACT_ERROR
                    else:
                        project_path, project_name = resolved
                        success, reply = await self._restart_project_now(project_name, project_path)
                        emoji = _REACT_OK if success else _REACT_ERROR
            else:
                emoji = _REACT_QUESTION

        await _clear_reaction(message, _REACT_THINKING, self.user)
        await _react(message, emoji)
        await message.reply(reply)

    async def _todo_add_command(self, args: list[str]) -> tuple[str, str]:
        cli_name, project, task, priority = self._parse_todo_add_args(args)
        raw_item = TodoItem(
            item_id="manual",
            priority=priority,
            cli=cli_name,
            project=project,
            task=task,
        )
        prepared, issue = prepare_todo_item(raw_item, self.config)
        if issue is not None:
            return f"❌ {issue.message}", _REACT_ERROR

        stored_item = TodoItem(
            item_id="manual",
            priority=priority,
            cli=display_todo_cli(cli_name),
            project=prepared.project_name,
            task=task,
        )
        add_todo_item(self.config.todo.file, stored_item)

        suffix = " It will run on the next queue pass." if self.todo_executor.is_running() else ""
        return (
            f"✅ Added todo item: P{priority} `{stored_item.cli}` | "
            f"`{stored_item.project}` | {stored_item.task}{suffix}"
        ), _REACT_OK

    async def _handle_message(self, message: discord.Message, content: str) -> None:
        try:
            decision = await self.llm_router.route(content)
        except Exception as exc:
            logger.exception("LLM routing failed: %s", exc)
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await _react(message, _REACT_ERROR)
            await message.reply(f"❌ Router error: {exc}")
            return

        if decision.tool == "ask_clarification":
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await _react(message, _REACT_QUESTION)
            await message.reply(f"🤔 {decision.args.get('question', '')}")
            return

        if decision.tool == "list_projects":
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await message.reply(format_project_list(self.config.projects))
            return

        if decision.tool == "reply":
            text = decision.args.get("text", "")
            await _clear_reaction(message, _REACT_THINKING, self.user)
            if text:
                await message.reply(text)
            return

        if decision.tool == "run_cli":
            await self._run_cli(message, decision.args)
            return

        if decision.tool == "run_pipeline":
            await self._run_pipeline(message, decision.args)
            return

        if decision.tool == "todo_add":
            await self._todo_add_from_tool(message, decision.args)
            return

        if decision.tool == "run_shell":
            await self._run_shell(message, decision.args)
            return

        if decision.tool == "read_context":
            await self._read_context(message, decision.args)
            return

        if decision.tool == "read_files":
            await self._read_files(message, decision.args)
            return

        if decision.tool == "analyze_project":
            await self._analyze_project(message, decision.args)
            return

        await _clear_reaction(message, _REACT_THINKING, self.user)
        await message.reply(f"🤷 Unknown action: `{decision.tool}`")

    async def _run_cli(self, message: discord.Message, args: dict) -> None:
        cli_key = args.get("cli", "claude_code")
        task = args.get("task", message.content)
        project_arg = args.get("project", "")
        files = [str(v) for v in (args.get("files") or [])]

        resolved = await self._resolve_project(message, project_arg)
        if resolved is None:
            return
        project_path, project_name = resolved

        busy_message = self._project_busy_message(project_name)
        if busy_message:
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await message.reply(busy_message)
            return

        if self.task_manager.is_cli_busy(cli_key):
            info = self.task_manager.current_cli_info(cli_key)
            await _clear_reaction(message, _REACT_THINKING, self.user)
            target = info.project if info is not None else "another project"
            await message.reply(
                f"⏳ CLI `{cli_key}` is already running on `{target}`. "
                f"Use `/cancel` to stop it."
            )
            return

        try:
            adapter, run, task_prompt = self._prepare_cli_execution(
                cli_key=cli_key,
                task=task,
                project_path=project_path,
                project_name=project_name,
                workflow="ad_hoc",
                role="coder",
                source="run_cli",
                files=files,
                metadata={"cli": cli_key, "source": "run_cli", "files": files},
            )
        except RuntimeError as exc:
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await _react(message, _REACT_ERROR)
            await message.reply(f"❌ {exc}")
            return

        await message.reply(
            f"🚀 Starting **{cli_key}** on `{project_name}`...\n"
            f"> {_clip(task, 150)}\n"
            f"Run: `{run.run_id}`\n"
            f"Logs: `{run.run_dir / 'timeline.md'}`"
        )

        project_cfg = self._project_profile(project_name, project_path)
        snapshot = capture_project_snapshot(project_path) if project_cfg.auto_restart else None
        append_workflow_event(
            run,
            stage="coder",
            status="started",
            message=f"Ad-hoc coding task started on `{cli_key}`.",
            details={"cli": cli_key, "source": "run_cli"},
        )
        result = await self.task_manager.execute(
            adapter=adapter,
            task=task_prompt,
            project_path=project_path,
            project_name=project_name,
            channel=message.channel,
            workflow="ad_hoc",
            run_id=run.run_id,
            log_path=str(run.run_dir / "timeline.md"),
        )

        write_artifact(run, "transcript.md", result.transcript or "(no output)")
        restart_result = AutoRestartResult()
        if result.returncode == 0:
            restart_result = await self._maybe_auto_restart_project(
                project_name=project_name,
                project_path=project_path,
                snapshot=snapshot,
                channel=message.channel,
            )
        await _clear_reaction(message, _REACT_THINKING, self.user)
        overall_success = result.returncode == 0 and not restart_result.failed
        summary = self._summarize_transcript(result.transcript)
        if restart_result.attempted:
            summary = " | ".join(part for part in [summary, restart_result.message] if part)
        append_workflow_event(
            run,
            stage="coder",
            status="completed" if overall_success else "failed",
            message="Ad-hoc coding task finished.",
            details={"returncode": result.returncode},
        )
        set_workflow_status(
            run,
            status="succeeded" if overall_success else "failed",
            summary=summary,
            extra={"returncode": result.returncode},
        )
        await _react(message, _REACT_OK if overall_success else _REACT_ERROR)

    async def _run_pipeline(self, message: discord.Message, args: dict) -> None:
        task = args.get("task", message.content).strip()
        project_arg = args.get("project", "")

        if not task:
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await _react(message, _REACT_ERROR)
            await message.reply("❌ `run_pipeline` needs a task.")
            return

        resolved = await self._resolve_project(message, project_arg)
        if resolved is None:
            return
        project_path, project_name = resolved

        busy_message = self._project_busy_message(project_name)
        if busy_message:
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await _react(message, _REACT_ERROR)
            await message.reply(busy_message)
            return

        await _clear_reaction(message, _REACT_THINKING, self.user)
        result = await self._run_feature_pipeline(
            project_name=project_name,
            project_path=project_path,
            task=task,
            channel=message.channel,
            source="run_pipeline",
        )
        await _react(message, _REACT_OK if result.success else _REACT_ERROR)

    async def _todo_add_from_tool(self, message: discord.Message, args: dict) -> None:
        cli_name = display_todo_cli(str(args.get("cli", "")).strip() or "claude_code")
        project = str(args.get("project", "")).strip()
        task = str(args.get("task", "")).strip()
        priority = int(args.get("priority", 3) or 3)

        if not project or not task:
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await _react(message, _REACT_ERROR)
            await message.reply("❌ `todo_add` needs `project` and `task`.")
            return

        reply, emoji = await self._todo_add_command([cli_name, project, task, "--priority", str(priority)])
        await _clear_reaction(message, _REACT_THINKING, self.user)
        await _react(message, emoji)
        await message.reply(reply)

    async def _run_shell(self, message: discord.Message, args: dict) -> None:
        command = args.get("command", "").strip()
        shell = args.get("shell", "auto")
        working_dir = args.get("working_dir") or None

        if not command:
            await message.reply("❌ No command provided.")
            return

        blocked, reason = is_command_blocked(command)
        if blocked:
            await message.reply(
                f"🚫 **Command blocked** — `{reason}` is on the safety blocklist.\n"
                f"This protects against accidental destructive operations.\n"
                f"If you really need this, run it manually in your terminal."
            )
            return

        shell_label = shell if shell != "auto" else self._platform.default_shell
        await message.reply(f"🔧 Running in `{shell_label}`: `{command}`")

        result = await run_shell(
            command=command,
            shell=shell,
            working_dir=working_dir,
            timeout=self.config.shell.timeout,
            platform_info=self._platform,
        )

        success = result.returncode == 0
        icon = "✅" if success else "❌"
        output = result.output or "(no output)"

        await _clear_reaction(message, _REACT_THINKING, self.user)
        await _react(message, _REACT_OK if success else _REACT_ERROR)

        chunks = _split_chunks(output)
        for i, chunk in enumerate(chunks):
            header = f"{icon} Exit `{result.returncode}`\n" if i == 0 else ""
            await message.reply(f"{header}```\n{chunk}\n```")
            if i < len(chunks) - 1:
                await asyncio.sleep(1)

    async def _read_context(self, message: discord.Message, args: dict) -> None:
        project_arg = args.get("project", "")
        resolved = await self._resolve_project(message, project_arg)
        if resolved is None:
            return
        project_path, project_name = resolved

        context = load_project_context(project_path, self.config, project_name)
        await _clear_reaction(message, _REACT_THINKING, self.user)

        if not context:
            await message.reply(
                f"ℹ️ No context files found for `{project_name}` at `{project_path}`."
            )
            return

        await _react(message, _REACT_OK)
        await message.reply(
            f"📄 Context for **{project_name}**:\n```\n{_clip(context)}\n```"
        )

    async def _read_files(self, message: discord.Message, args: dict) -> None:
        project_arg = args.get("project", "")
        file_patterns = [str(v) for v in (args.get("files") or [])]
        max_files = int(args.get("max_files", 6) or 6)

        if not file_patterns:
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await _react(message, _REACT_ERROR)
            await message.reply("❌ `read_files` needs at least one file path or glob.")
            return

        resolved = await self._resolve_project(message, project_arg)
        if resolved is None:
            return
        project_path, project_name = resolved

        files = resolve_project_files(project_path, file_patterns, max_files=max_files)
        if not files:
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await _react(message, _REACT_ERROR)
            await message.reply(
                f"❌ No matching files found in `{project_name}` for: {_format_file_list(file_patterns)}"
            )
            return

        bundle, included = build_file_bundle(project_path, files, max_total_chars=8000)
        await _clear_reaction(message, _REACT_THINKING, self.user)
        await _react(message, _REACT_OK)
        await message.reply(
            f"📄 Files for **{project_name}** ({_format_file_list(included)}):\n"
            f"```\n{_clip(bundle)}\n```"
        )

    async def _analyze_project(self, message: discord.Message, args: dict) -> None:
        project_arg = args.get("project", "")
        goal = args.get("goal", "").strip()
        mode = args.get("mode", "analyze").strip() or "analyze"
        workflow_name = args.get("workflow", "analysis").strip() or "analysis"
        role_name = args.get("role", "reviewer").strip() or "reviewer"
        reviewer_cli = args.get("reviewer_cli", "").strip()
        file_hints = [str(v) for v in (args.get("file_hints") or [])]

        if not goal:
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await _react(message, _REACT_ERROR)
            await message.reply("❌ `analyze_project` needs a goal.")
            return

        resolved = await self._resolve_project(message, project_arg)
        if resolved is None:
            return
        project_path, project_name = resolved
        project_cfg = self._project_profile(project_name, project_path)

        busy_message = self._project_busy_message(project_name)
        if busy_message:
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await message.reply(busy_message)
            return

        selected_paths = select_analysis_files(
            project_path=project_path,
            project_cfg=project_cfg,
            goal=goal,
            file_hints=file_hints,
        )
        file_bundle, included = build_file_bundle(project_path, selected_paths)

        if not file_bundle:
            fallback_context = load_project_context(project_path, self.config, project_name)
            file_bundle = fallback_context

        cli_key = select_cli_for_role(
            role_name=role_name,
            config=self.config,
            project_name=project_name,
            preferred_cli=reviewer_cli,
        )
        # Fall back through available CLIs: selected -> claude_code -> others
        adapter = None
        for candidate in [cli_key, "claude_code", "gemini_cli", "qwen_cli"]:
            _cfg = getattr(self.config.cli, candidate, None)
            if _cfg and _cfg.enabled:
                _adapter = build_adapter(candidate, self.config)
                if _adapter.is_available():
                    if candidate != cli_key:
                        logger.warning("CLI %s unavailable, fell back to %s", cli_key, candidate)
                    cli_key = candidate
                    adapter = _adapter
                    break

        if adapter is None:
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await _react(message, _REACT_ERROR)
            await message.reply("❌ No enabled CLI agent found on PATH.")
            return

        if self.task_manager.is_cli_busy(cli_key):
            info = self.task_manager.current_cli_info(cli_key)
            await _clear_reaction(message, _REACT_THINKING, self.user)
            target = info.project if info is not None else "another project"
            await message.reply(
                f"⏳ CLI `{cli_key}` is already running on `{target}`. "
                f"Use `/cancel` to stop it."
            )
            return

        run = start_workflow_run(
            project_path=project_path,
            project_name=project_name,
            workflow=workflow_name,
            role=role_name,
            goal=goal,
            metadata={
                "mode": mode,
                "cli": cli_key,
                "file_hints": file_hints,
                "selected_files": included,
            },
        )
        write_artifact(
            run,
            "brief.md",
            f"# {mode.title()} Request\n\nGoal: {goal}\n\nRole: {role_name}\nWorkflow: {workflow_name}\n",
        )
        if included:
            write_artifact(
                run,
                "selected-files.md",
                "\n".join(f"- {path}" for path in included),
            )
        if file_bundle:
            write_artifact(run, "file-context.md", file_bundle)

        task_prompt = build_analysis_prompt(
            config=self.config,
            project_name=project_name,
            project_cfg=project_cfg,
            goal=goal,
            mode=mode,
            role_name=role_name,
            workflow_name=workflow_name,
            file_bundle=file_bundle,
            selected_files=included,
            run=run,
        )
        write_artifact(run, "task-prompt.md", task_prompt)

        await message.reply(
            f"🔎 Starting **{mode}** on `{project_name}` with **{cli_key}** "
            f"as `{role_name}`...\n"
            f"Files: {_format_file_list(included)}\n"
            f"Run: `{run.run_id}`\n"
            f"Logs: `{run.run_dir / 'timeline.md'}`"
        )

        append_workflow_event(
            run,
            stage=role_name,
            status="started",
            message=f"{mode.title()} run started on `{cli_key}`.",
            details={"cli": cli_key, "mode": mode},
        )
        result = await self.task_manager.execute(
            adapter=adapter,
            task=task_prompt,
            project_path=project_path,
            project_name=project_name,
            channel=message.channel,
            workflow=workflow_name,
            run_id=run.run_id,
            log_path=str(run.run_dir / "timeline.md"),
        )

        write_artifact(run, f"{mode}-report.md", result.transcript or "(no output)")
        append_workflow_event(
            run,
            stage=role_name,
            status="completed" if result.returncode == 0 else "failed",
            message=f"{mode.title()} run finished.",
            details={"cli": cli_key, "returncode": result.returncode},
        )
        set_workflow_status(
            run,
            status="succeeded" if result.returncode == 0 else "failed",
            summary=self._summarize_transcript(result.transcript),
            extra={"returncode": result.returncode},
        )
        await _clear_reaction(message, _REACT_THINKING, self.user)
        await _react(message, _REACT_OK if result.returncode == 0 else _REACT_ERROR)
