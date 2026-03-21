"""Discord bot client and on_message handler."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

import discord

from devbot.bot.commands import register_commands
from devbot.bot.formatter import format_project_list
from devbot.context.files import build_file_bundle, resolve_project_files, select_analysis_files
from devbot.context.loader import load_project_context
from devbot.context.project import resolve_project
from devbot.executor.adapters.claude_code import ClaudeCodeAdapter
from devbot.executor.adapters.codex import CodexAdapter
from devbot.executor.adapters.gemini_cli import GeminiCLIAdapter
from devbot.executor.adapters.qwen_cli import QwenCLIAdapter
from devbot.executor.manager import TaskManager
from devbot.executor.shell import is_command_blocked, run_shell
from devbot.executor.shell.platform import detect_platform
from devbot.llm.router import LLMRouter
from devbot.workflow.prompts import build_analysis_prompt, build_cli_task_prompt
from devbot.workflow.registry import select_cli_for_role
from devbot.workflow.store import start_workflow_run, write_artifact

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


def _format_file_list(files: list[str]) -> str:
    if not files:
        return "(none)"
    return ", ".join(files)


_ADAPTER_CLASSES = {
    "claude_code": ClaudeCodeAdapter,
    "codex": CodexAdapter,
    "qwen_cli": QwenCLIAdapter,
    "gemini_cli": GeminiCLIAdapter,
}


def _build_adapter(cli_key: str, config: "Config"):
    """Instantiate the right adapter from config."""
    cli_cfg = getattr(config.cli, cli_key, None)
    if cli_cfg is None:
        cli_cfg = getattr(config.cli, "claude_code")

    cls = _ADAPTER_CLASSES.get(cli_key, ClaudeCodeAdapter)
    return cls(
        command=cli_cfg.command,
        base_args=cli_cfg.base_args,
        autonomy_args=cli_cfg.autonomy_args,
        extra_args=cli_cfg.extra_args,
    )


class DevBotClient(discord.Client):
    def __init__(self, config: "Config"):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)

        self.config = config
        self.tree = discord.app_commands.CommandTree(self)
        self.task_manager = TaskManager(config)
        self.llm_router = LLMRouter(config)
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

        if self.task_manager.is_busy():
            await message.reply("⏳ A task is already running. Use `/cancel` to stop it.")
            return

        await _react(message, _REACT_THINKING)
        asyncio.ensure_future(self._handle_message(message, content))

    def _project_profile(self, project_name: str, project_path: str) -> "ProjectConfig":
        from devbot.config.settings import ProjectConfig

        return self.config.projects.get(project_name, ProjectConfig(path=Path(project_path)))

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
        project_cfg = self._project_profile(project_name, project_path)

        cli_cfg = getattr(self.config.cli, cli_key, None)
        if cli_cfg is None:
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await _react(message, _REACT_ERROR)
            await message.reply(f"❌ Unknown CLI: `{cli_key}`")
            return

        if not cli_cfg.enabled:
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await _react(message, _REACT_ERROR)
            await message.reply(f"❌ CLI `{cli_key}` is disabled in config.")
            return

        adapter = _build_adapter(cli_key, self.config)
        if not adapter.is_available():
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await _react(message, _REACT_ERROR)
            await message.reply(
                f"❌ `{cli_cfg.command}` not found on PATH. Install it or check your config."
            )
            return

        run = start_workflow_run(
            project_path=project_path,
            project_name=project_name,
            workflow="ad_hoc",
            role="coder",
            goal=task,
            metadata={"cli": cli_key, "source": "run_cli", "files": files},
        )
        project_context = load_project_context(project_path, self.config, project_name)
        task_prompt = build_cli_task_prompt(
            task=task,
            project_name=project_name,
            project_cfg=project_cfg,
            project_context=project_context,
            files=files,
            run=run,
        )

        write_artifact(run, "request.md", task)
        if project_context:
            write_artifact(run, "project-context.md", project_context)
        write_artifact(run, "task-prompt.md", task_prompt)

        await message.reply(
            f"🚀 Starting **{cli_key}** on `{project_name}`...\n"
            f"> {_clip(task, 150)}\n"
            f"Run: `{run.run_id}`"
        )

        result = await self.task_manager.execute(
            adapter=adapter,
            task=task_prompt,
            project_path=project_path,
            project_name=project_name,
            channel=message.channel,
        )

        write_artifact(run, "transcript.md", result.transcript or "(no output)")
        await _clear_reaction(message, _REACT_THINKING, self.user)
        await _react(message, _REACT_OK if result.returncode == 0 else _REACT_ERROR)

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
        output = _clip(result.output or "(no output)")

        await _clear_reaction(message, _REACT_THINKING, self.user)
        await _react(message, _REACT_OK if success else _REACT_ERROR)
        await message.reply(f"{icon} Exit `{result.returncode}`\n```\n{output}\n```")

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
        cli_cfg = getattr(self.config.cli, cli_key, None)
        adapter = _build_adapter(cli_key, self.config)

        if cli_cfg is None or not cli_cfg.enabled:
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await _react(message, _REACT_ERROR)
            await message.reply(f"❌ Reviewer CLI `{cli_key}` is not enabled.")
            return
        if not adapter.is_available():
            await _clear_reaction(message, _REACT_THINKING, self.user)
            await _react(message, _REACT_ERROR)
            await message.reply(f"❌ `{cli_cfg.command}` not found on PATH.")
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
            f"Run: `{run.run_id}`"
        )

        result = await self.task_manager.execute(
            adapter=adapter,
            task=task_prompt,
            project_path=project_path,
            project_name=project_name,
            channel=message.channel,
        )

        write_artifact(run, f"{mode}-report.md", result.transcript or "(no output)")
        await _clear_reaction(message, _REACT_THINKING, self.user)
        await _react(message, _REACT_OK if result.returncode == 0 else _REACT_ERROR)
