"""Todo file parsing and writing."""

from __future__ import annotations

import re
from pathlib import Path

from devbot.todo.models import TodoItem
from devbot.todo.validator import display_todo_cli


_SECTION_RE = re.compile(r"^##\s+Priority\s+(\d+)(?:\s+[—-]\s+.*)?\s*$")
_ITEM_RE = re.compile(
    r"^- \[(?P<done>[ xX])\]\s+`(?P<cli>[^`]+)`\s+\|\s+`(?P<project>[^`]+)`\s+\|\s+(?P<task>.+?)\s*$"
)
_PRIORITY_LABELS = {
    1: "Critical",
    2: "High",
    3: "Normal",
}


def parse_todo_file(path: Path) -> list[TodoItem]:
    if not path.exists():
        return []

    items: list[TodoItem] = []
    priority = 3
    order = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        section_match = _SECTION_RE.match(line.strip())
        if section_match:
            priority = int(section_match.group(1))
            continue

        item_match = _ITEM_RE.match(line.rstrip())
        if not item_match:
            continue
        if item_match.group("done").lower() == "x":
            continue

        order += 1
        items.append(
            TodoItem(
                item_id=f"todo-{order}",
                priority=priority,
                cli=item_match.group("cli").strip(),
                project=item_match.group("project").strip(),
                task=item_match.group("task").strip(),
                order=order,
            )
        )
    return items


def write_todo_file(path: Path, items: list[TodoItem]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = ["# DevBot Todo List", ""]
    ordered = sorted(items, key=lambda item: (item.priority, item.order, item.project, item.task))

    for priority in sorted(_PRIORITY_LABELS):
        bucket = [item for item in ordered if item.priority == priority]
        if not bucket:
            continue

        lines.append(f"## Priority {priority} - {_PRIORITY_LABELS[priority]}")
        for item in bucket:
            cli = display_todo_cli(item.cli)
            lines.append(f"- [ ] `{cli}` | `{item.project}` | {item.task}")
        lines.append("")

    if lines[-1] != "":
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def add_todo_item(path: Path, item: TodoItem) -> None:
    items = parse_todo_file(path)
    next_order = max((existing.order for existing in items), default=0) + 1
    item.order = next_order
    items.append(item)
    write_todo_file(path, items)


def remove_todo_item(path: Path, item: TodoItem) -> bool:
    items = parse_todo_file(path)
    kept: list[TodoItem] = []
    removed = False

    for existing in items:
        if not removed and _same_item(existing, item):
            removed = True
            continue
        kept.append(existing)

    if removed:
        write_todo_file(path, kept)
    return removed


def _same_item(left: TodoItem, right: TodoItem) -> bool:
    return (
        left.priority == right.priority
        and display_todo_cli(left.cli) == display_todo_cli(right.cli)
        and left.project == right.project
        and left.task == right.task
    )
