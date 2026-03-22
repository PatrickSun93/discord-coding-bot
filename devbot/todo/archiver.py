"""Todo archive writer."""

from __future__ import annotations

from pathlib import Path

from devbot.todo.models import TodoRunResult
from devbot.todo.validator import display_todo_cli


def archive_todo_result(path: Path, result: TodoRunResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    if not existing.strip():
        existing = "# DevBot - Completed Tasks\n\n"

    date = result.completed_at.split(" ", 1)[0]
    if f"## {date}\n" not in existing:
        if not existing.endswith("\n"):
            existing += "\n"
        existing += f"## {date}\n\n"
    elif not existing.endswith("\n"):
        existing += "\n"

    status_text = _status_line(result.status, result.returncode)
    summary = result.summary.strip()
    lines = [
        f"- [x] `{display_todo_cli(result.item.item.cli)}` | `{result.item.project_name}` | {result.item.item.task}",
        f"  - **Status**: {status_text}",
        f"  - **Duration**: {result.duration:.0f}s",
        f"  - **Completed**: {result.completed_at}",
    ]
    if summary:
        lines.append(f"  - **Summary**: {summary}")

    existing += "\n".join(lines) + "\n\n"
    path.write_text(existing, encoding="utf-8")


def _status_line(status: str, returncode: int | None) -> str:
    if status == "success":
        code_suffix = f" (exit {returncode})" if returncode is not None else ""
        return f"Success{code_suffix}"
    if status == "cancelled":
        return "Cancelled"
    code_suffix = f" (exit {returncode})" if returncode is not None else ""
    return f"Failed{code_suffix}"
