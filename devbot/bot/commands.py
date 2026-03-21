"""Slash commands: /status /cancel /projects /project /config /history /shells /doctor"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands

from devbot.bot.formatter import format_project_list, format_status
from devbot.executor.manager import TaskManager
from devbot.llm.router import LLMRouter
from devbot.workflow.registry import load_role_registry, load_workflow_registry

if TYPE_CHECKING:
    from devbot.bot.client import DevBotClient

logger = logging.getLogger(__name__)


def register_commands(bot: "DevBotClient") -> None:
    tree = bot.tree

    @tree.command(name="status", description="Show the current task status.")
    async def status_cmd(interaction: discord.Interaction) -> None:
        msg = format_status(bot.task_manager.current_info(), bot.task_manager.is_busy())
        await interaction.response.send_message(msg, ephemeral=True)

    @tree.command(name="cancel", description="Cancel the currently running task.")
    async def cancel_cmd(interaction: discord.Interaction) -> None:
        if interaction.user.id != bot.config.discord.owner_id:
            await interaction.response.send_message("⛔ Not authorized.", ephemeral=True)
            return
        cancelled = await bot.task_manager.cancel()
        if cancelled:
            await interaction.response.send_message("🛑 Task cancelled.", ephemeral=False)
        else:
            await interaction.response.send_message("Nothing is running.", ephemeral=True)

    @tree.command(name="projects", description="List all registered projects.")
    async def projects_cmd(interaction: discord.Interaction) -> None:
        msg = format_project_list(bot.config.projects)
        await interaction.response.send_message(msg, ephemeral=True)

    project_group = app_commands.Group(name="project", description="Manage projects.")

    @project_group.command(name="add", description="Register a new project.")
    @app_commands.describe(name="Short project name", path="Absolute path to project directory")
    async def project_add(interaction: discord.Interaction, name: str, path: str) -> None:
        if interaction.user.id != bot.config.discord.owner_id:
            await interaction.response.send_message("⛔ Not authorized.", ephemeral=True)
            return
        from pathlib import Path
        from devbot.config.settings import ProjectConfig
        p = Path(path)
        if not p.exists() or not p.is_dir():
            await interaction.response.send_message(
                f"❌ Path `{path}` does not exist or is not a directory.", ephemeral=True
            )
            return
        bot.config.projects[name] = ProjectConfig(path=p)
        await interaction.response.send_message(
            f"✅ Project **{name}** registered at `{path}`.", ephemeral=False
        )

    tree.add_command(project_group)

    config_group = app_commands.Group(name="config", description="Bot configuration.")

    @config_group.command(name="reload", description="Hot-reload config from disk.")
    async def config_reload(interaction: discord.Interaction) -> None:
        if interaction.user.id != bot.config.discord.owner_id:
            await interaction.response.send_message("⛔ Not authorized.", ephemeral=True)
            return
        try:
            from devbot.config.settings import load_config
            bot.config = load_config()
            bot.task_manager = TaskManager(bot.config)
            bot.llm_router = LLMRouter(bot.config)
            # Re-detect platform in case shell config changed
            from devbot.executor.shell.platform import detect_platform
            bot._platform = detect_platform(
                preferred=bot.config.shell.default,
                wsl_distro=bot.config.shell.wsl_distro,
            )
            await interaction.response.send_message("✅ Config reloaded.", ephemeral=True)
        except Exception as exc:
            await interaction.response.send_message(f"❌ Failed to reload: {exc}", ephemeral=True)

    tree.add_command(config_group)

    @tree.command(name="history", description="Show recent task history (last 10).")
    async def history_cmd(interaction: discord.Interaction) -> None:
        if interaction.user.id != bot.config.discord.owner_id:
            await interaction.response.send_message("⛔ Not authorized.", ephemeral=True)
            return
        try:
            from devbot.history import get_recent
            import time as _time
            records = get_recent(10)
        except Exception as exc:
            await interaction.response.send_message(f"❌ Could not load history: {exc}", ephemeral=True)
            return
        if not records:
            await interaction.response.send_message("No task history yet.", ephemeral=True)
            return
        lines = []
        for r in records:
            status = "✅" if r.success else "❌"
            age = int(_time.time() - r.ts)
            lines.append(
                f"{status} **{r.cli_name}** on `{r.project}` — {r.duration:.0f}s — {age}s ago\n"
                f"  _{r.task[:80]}_"
            )
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @tree.command(name="shells", description="Show OS, available shells, and default shell.")
    async def shells_cmd(interaction: discord.Interaction) -> None:
        info = bot._platform
        lines = [
            f"**OS:** {info.os_name}",
            f"**Default shell:** `{info.default_shell}`",
            f"**Available shells:** {', '.join(f'`{s}`' for s in info.available_shells) or '(none detected)'}",
            f"**WSL available:** {'yes' if info.has_wsl else 'no'}",
        ]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @tree.command(name="doctor", description="Check CLIs, shells, LLM connectivity.")
    async def doctor_cmd(interaction: discord.Interaction) -> None:
        if interaction.user.id != bot.config.discord.owner_id:
            await interaction.response.send_message("⛔ Not authorized.", ephemeral=True)
            return

        import shutil
        lines: list[str] = ["**DevBot Doctor**"]

        # CLIs
        for cli_key, binary in [
            ("claude_code", "claude"),
            ("codex", "codex"),
            ("gemini_cli", "gemini"),
            ("qwen_cli", "qwen"),
        ]:
            found = shutil.which(binary)
            icon = "✅" if found else "⚠️"
            lines.append(f"{icon} `{binary}`: {'found' if found else 'not on PATH'}")

        # gh CLI
        gh = shutil.which("gh")
        lines.append(f"{'✅' if gh else '⚠️'} `gh`: {'found' if gh else 'not on PATH (needed for PR creation)'}")

        # Docker
        docker = shutil.which("docker")
        lines.append(f"{'✅' if docker else '⚠️'} `docker`: {'found' if docker else 'not on PATH (optional)'}")

        # WSL (Windows only)
        info = bot._platform
        if info.os_name == "Windows":
            lines.append(f"{'✅' if info.has_wsl else '⚠️'} WSL: {'available' if info.has_wsl else 'not found (bash via WSL unavailable)'}")

        # Shells
        lines.append(f"🐚 Default shell: `{info.default_shell}` | Available: {', '.join(f'`{s}`' for s in info.available_shells)}")

        # Projects
        lines.append(f"📁 Registered projects: {len(bot.config.projects)}")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @tree.command(name="roles", description="List workflow roles and their preferred CLIs.")
    async def roles_cmd(interaction: discord.Interaction) -> None:
        registry = load_role_registry(bot.config)
        lines = []
        for name, role in registry.items():
            preferred = ", ".join(f"`{cli}`" for cli in role.preferred_clis) or "(auto)"
            lines.append(f"**{name}** — {role.purpose or 'No purpose set.'} Preferred: {preferred}")
        await interaction.response.send_message("\n".join(lines) or "No roles configured.", ephemeral=True)

    @tree.command(name="workflows", description="List available workflow definitions.")
    async def workflows_cmd(interaction: discord.Interaction) -> None:
        registry = load_workflow_registry(bot.config)
        lines = []
        for name, workflow in registry.items():
            stages = " -> ".join(workflow.stages) or "(no stages)"
            lines.append(f"**{name}** — {workflow.description or 'No description set.'} Stages: `{stages}`")
        await interaction.response.send_message("\n".join(lines) or "No workflows configured.", ephemeral=True)
