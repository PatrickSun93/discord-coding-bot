"""Project change tracking and auto-restart planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from devbot.config.settings import Config, ProjectConfig


_IGNORED_DIRS = {
    ".git",
    ".devbot",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".next",
    ".nuxt",
    ".turbo",
    ".cache",
    "node_modules",
    "dist",
    "build",
    "coverage",
    ".venv",
    "venv",
}
_NON_RESTART_EXTENSIONS = {
    ".md",
    ".rst",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".webp",
    ".bmp",
    ".pdf",
}
_NON_RESTART_FILENAMES = {
    "readme",
    "readme.md",
    "license",
    "license.md",
    "contributing.md",
    "changelog.md",
}


@dataclass
class ProjectSnapshot:
    files: dict[str, tuple[int, int]] = field(default_factory=dict)


@dataclass
class AutoRestartPlan:
    command: str
    shell: str
    source: str


@dataclass
class AutoRestartResult:
    attempted: bool = False
    restarted: bool = False
    message: str = ""
    output: str = ""
    changed_paths: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.attempted and not self.restarted


def capture_project_snapshot(project_path: str) -> ProjectSnapshot:
    root = Path(project_path)
    snapshot: dict[str, tuple[int, int]] = {}

    if not root.exists():
        return ProjectSnapshot()

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name
            for name in dirnames
            if name not in _IGNORED_DIRS
        ]
        current_dir = Path(dirpath)
        for filename in filenames:
            path = current_dir / filename
            try:
                stat = path.stat()
            except OSError:
                continue
            rel = path.relative_to(root).as_posix()
            snapshot[rel] = (stat.st_mtime_ns, stat.st_size)

    return ProjectSnapshot(files=snapshot)


def detect_restart_relevant_changes(
    before: ProjectSnapshot,
    after: ProjectSnapshot,
    limit: int = 20,
) -> list[str]:
    changed: list[str] = []
    all_paths = set(before.files) | set(after.files)
    for rel_path in sorted(all_paths):
        if before.files.get(rel_path) == after.files.get(rel_path):
            continue
        if not is_restart_relevant_path(rel_path):
            continue
        changed.append(rel_path)
        if len(changed) >= limit:
            break
    return changed


def is_restart_relevant_path(rel_path: str) -> bool:
    path = Path(rel_path)
    lowered_name = path.name.lower()
    if lowered_name in _NON_RESTART_FILENAMES:
        return False
    if any(part in _IGNORED_DIRS for part in path.parts):
        return False
    if path.suffix.lower() in _NON_RESTART_EXTENSIONS:
        return False
    if path.parts and path.parts[0].lower() == "docs" and path.suffix.lower() in {".md", ".txt", ".rst"}:
        return False
    return True


def resolve_auto_restart_plan(
    config: "Config",
    project_cfg: "ProjectConfig",
    project_name: str,
    require_enabled: bool = True,
) -> tuple[AutoRestartPlan | None, str | None]:
    if require_enabled and not project_cfg.auto_restart:
        return None, None

    restart_service = project_cfg.restart_service.strip()
    if restart_service:
        service_cfg = config.services.get(restart_service)
        if service_cfg and service_cfg.commands.get("restart"):
            return (
                AutoRestartPlan(
                    command=service_cfg.commands["restart"],
                    shell=service_cfg.shell,
                    source=f"service `{restart_service}`",
                ),
                None,
            )
        return None, f"restart_service `{restart_service}` is missing or has no restart command."

    if project_cfg.commands.restart:
        return (
            AutoRestartPlan(
                command=project_cfg.commands.restart,
                shell=project_cfg.commands.restart_shell or "auto",
                source="project restart command",
            ),
            None,
        )

    service_cfg = config.services.get(project_name)
    if service_cfg and service_cfg.commands.get("restart"):
        return (
            AutoRestartPlan(
                command=service_cfg.commands["restart"],
                shell=service_cfg.shell,
                source=f"service `{project_name}`",
            ),
            None,
        )

    return None, (
        f"Auto-restart is enabled for `{project_name}` but no restart command is configured. "
        "Set `projects.<name>.commands.restart` or `projects.<name>.restart_service`."
    )
