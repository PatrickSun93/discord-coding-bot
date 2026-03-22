"""Discord message formatting helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from devbot.todo.models import TodoItem, TodoQueueStatus
from devbot.todo.validator import display_todo_cli
from devbot.workflow.models import ActiveWorkflowStatus

if TYPE_CHECKING:
    pass


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
        lines.append(f"\n**{project}** — `{info.cli_name}` — `{elapsed:.0f}s`")
        lines.append(f"  {info.task[:200]}")
        meta: list[str] = []
        if getattr(info, "workflow", ""):
            meta.append(f"workflow `{info.workflow}`")
        if getattr(info, "run_id", ""):
            meta.append(f"run `{info.run_id}`")
        if getattr(info, "log_path", ""):
            meta.append(f"logs `{info.log_path}`")
        if meta:
            lines.append("  " + " | ".join(meta))
    return "\n".join(lines)


def format_pipeline_status(statuses: list[ActiveWorkflowStatus]) -> str:
    if not statuses:
        return ""
    lines = [f"🚀 **Feature Pipelines** ({len(statuses)} running)"]
    for item in statuses:
        stage = item.stage or item.workflow
        state = item.status or "running"
        summary = item.message or "Pipeline is active."
        lines.append(
            f"\n**{item.project_name}** — `{stage}` — `{state}`\n"
            f"  {summary}\n"
            f"  run `{item.run_id}` | logs `{item.log_path}`"
        )
    return "\n".join(lines)


def format_combined_status(
    tasks: dict,
    todo_status: TodoQueueStatus,
    pipeline_statuses: list[ActiveWorkflowStatus] | None = None,
) -> str:
    sections: list[str] = []
    task_text = format_status(tasks)
    if tasks:
        sections.append(task_text)
    pipeline_text = format_pipeline_status(pipeline_statuses or [])
    if pipeline_text:
        sections.append(pipeline_text)
    if todo_status.is_running or todo_status.pending_items:
        sections.append(format_todo_status(todo_status))
    return "\n\n".join(sections) or "💤 No task running."


def format_todo_list(items: list[TodoItem]) -> str:
    if not items:
        return "📋 No pending todo items."

    lines = [f"📋 **Todo Queue** ({len(items)} item{'s' if len(items) != 1 else ''})"]
    for priority in (1, 2, 3):
        bucket = [item for item in items if item.priority == priority]
        if not bucket:
            continue
        lines.append(f"\n**Priority {priority}**")
        for item in bucket:
            lines.append(f"- `{display_todo_cli(item.cli)}` | `{item.project}` | {item.task}")
    return "\n".join(lines)


def format_todo_status(status: TodoQueueStatus) -> str:
    pending_count = len(status.pending_items)
    if not status.is_running:
        if pending_count == 0:
            return "📋 Todo queue idle."
        return f"📋 Todo queue idle. Pending: {pending_count}."

    elapsed = status.elapsed()
    lines = [
        f"📋 **Todo Queue Running** — {elapsed:.0f}s",
        (
            f"Completed: {status.completed} | "
            f"Failed: {status.failed} | "
            f"Cancelled: {status.cancelled} | "
            f"Pending: {pending_count}"
        ),
    ]
    if status.current_priority is not None:
        lines.append(f"Current priority: {status.current_priority}")
    if status.running_items:
        lines.append("Active:")
        for cli_key, item in status.running_items.items():
            lines.append(f"- `{display_todo_cli(cli_key)}` -> `{item.project_name}` | {item.item.task}")
    return "\n".join(lines)


def format_todo_validation_errors(errors: list[str]) -> str:
    if not errors:
        return "No todo validation errors."
    lines = ["❌ Todo validation failed:"]
    lines.extend(f"- {error}" for error in errors)
    return "\n".join(lines)
