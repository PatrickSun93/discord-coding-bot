"""Project registry — resolves names to paths."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from devbot.config.settings import Config


def resolve_project(
    name_or_path: str,
    config: "Config",
) -> tuple[str, str]:
    """Return (resolved_path, display_name) for a project name or absolute path.

    Raises ValueError if the project cannot be resolved.
    """
    # Try as a registered project name first (case-insensitive)
    lower = name_or_path.lower()
    for proj_name, proj_cfg in config.projects.items():
        if proj_name.lower() == lower:
            return str(proj_cfg.path), proj_name

    # Try as a direct path
    p = Path(name_or_path)
    if p.exists() and p.is_dir():
        return str(p), name_or_path

    raise ValueError(
        f"Unknown project '{name_or_path}'. "
        f"Known projects: {list(config.projects.keys()) or ['(none registered)']}. "
        f"You can also pass an absolute path."
    )
