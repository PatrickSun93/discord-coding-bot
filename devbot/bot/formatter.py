"""Discord message formatting helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from devbot.config.settings import Config


def format_project_list(projects: dict) -> str:
    if not projects:
        return "No projects registered. Add them to your config or use `/project add`."
    lines = ["**Registered Projects:**"]
    for name, cfg in projects.items():
        desc = f" — {cfg.description}" if cfg.description else ""
        lines.append(f"• **{name}**: `{cfg.path}`{desc}")
    return "\n".join(lines)


def format_status(task_info, is_busy: bool) -> str:
    if not is_busy or task_info is None:
        return "💤 No task running."
    elapsed = task_info.elapsed()
    return (
        f"⚡ **Running**\n"
        f"CLI: `{task_info.cli_name}` | Project: `{task_info.project}`\n"
        f"Elapsed: `{elapsed:.0f}s`\n"
        f"Task: {task_info.task[:200]}"
    )
