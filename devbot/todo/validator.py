"""Todo item normalization and validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from devbot.context.project import resolve_project
from devbot.executor.adapters.factory import build_adapter
from devbot.todo.models import PreparedTodoItem, TodoItem, TodoValidationIssue
from devbot.workflow.registry import select_cli_for_role

if TYPE_CHECKING:
    from devbot.config.settings import Config


_CLI_ALIASES = {
    "claude": "claude_code",
    "claude_code": "claude_code",
    "codex": "codex",
    "gemini": "gemini_cli",
    "gemini_cli": "gemini_cli",
    "qwen": "qwen_cli",
    "qwen_cli": "qwen_cli",
    "pipeline": "pipeline",
}
_CLI_DISPLAY = {
    "claude_code": "claude",
    "codex": "codex",
    "gemini_cli": "gemini",
    "qwen_cli": "qwen",
    "pipeline": "pipeline",
}
def normalize_todo_cli(name: str) -> str:
    return _CLI_ALIASES.get(name.strip().lower(), "")


def display_todo_cli(name: str) -> str:
    normalized = normalize_todo_cli(name) or name.strip().lower()
    return _CLI_DISPLAY.get(normalized, normalized)


def prepare_todo_items(
    items: list[TodoItem],
    config: "Config",
) -> tuple[list[PreparedTodoItem], list[TodoValidationIssue]]:
    prepared: list[PreparedTodoItem] = []
    issues: list[TodoValidationIssue] = []
    for item in items:
        candidate, problem = prepare_todo_item(item, config)
        if candidate is not None:
            prepared.append(candidate)
        if problem is not None:
            issues.append(problem)
    return prepared, issues


def prepare_todo_item(
    item: TodoItem,
    config: "Config",
) -> tuple[PreparedTodoItem | None, TodoValidationIssue | None]:
    if item.priority not in (1, 2, 3):
        return None, TodoValidationIssue(item=item, message="Priority must be 1, 2, or 3.")

    cli_name = normalize_todo_cli(item.cli)
    if not cli_name:
        return None, TodoValidationIssue(
            item=item,
            message=(
                "Unknown CLI. Use one of: claude, codex, gemini, qwen, pipeline."
            ),
        )

    try:
        project_path, project_name = resolve_project(item.project, config)
    except ValueError as exc:
        return None, TodoValidationIssue(item=item, message=str(exc))

    mode = "cli"
    cli_key = cli_name
    if cli_name == "pipeline":
        mode = "pipeline"
        cli_key = select_cli_for_role("coder", config, project_name=project_name)

    cli_cfg = getattr(config.cli, cli_key, None)
    if cli_cfg is None:
        return None, TodoValidationIssue(
            item=item,
            message=f"CLI `{cli_key}` is not configured.",
        )
    if not cli_cfg.enabled:
        return None, TodoValidationIssue(
            item=item,
            message=f"CLI `{cli_key}` is disabled in config.",
        )

    adapter = build_adapter(cli_key, config)
    if not adapter.is_available():
        return None, TodoValidationIssue(
            item=item,
            message=f"`{cli_cfg.command}` is not on PATH.",
        )

    return (
        PreparedTodoItem(
            item=item,
            cli_key=cli_key,
            project_path=project_path,
            project_name=project_name,
            mode=mode,
        ),
        None,
    )
