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


def format_status(tasks: dict) -> str:
    if not tasks:
        return "💤 No task running."
    lines = [f"⚡ **Running** ({len(tasks)} task{'s' if len(tasks) != 1 else ''})"]
    for project, info in tasks.items():
        elapsed = info.elapsed()
        lines.append(
            f"\n**{project}** — `{info.cli_name}` — `{elapsed:.0f}s`\n"
            f"  {info.task[:200]}"
        )
    return "\n".join(lines)
