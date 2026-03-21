"""Context file loader — reads core agent context files from project root."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from devbot.config.settings import Config, ProjectConfig


_DEFAULT_CONTEXT_FILES = [
    "claude.md",
    "CLAUDE.md",
    "AGENTS.md",
    "agents.md",
    "GEMINI.md",
    "gemini.md",
    "README.md",
]


def load_project_context(project_path: str, config: "Config", project_name: str = "") -> str:
    """Build a context string from the project's context files.

    Reads whichever of the configured context files exist and concatenates them.
    """
    path = Path(project_path)
    proj_cfg = config.projects.get(project_name)
    if proj_cfg:
        context_files = proj_cfg.context_files or proj_cfg.docs.agent_context or _DEFAULT_CONTEXT_FILES
    else:
        context_files = _DEFAULT_CONTEXT_FILES

    # Also check for per-project .devbot.yaml overrides
    devbot_yaml = path / ".devbot.yaml"
    if devbot_yaml.exists():
        try:
            import yaml
            with open(devbot_yaml, encoding="utf-8") as f:
                overrides = yaml.safe_load(f) or {}
            if "context_files" in overrides:
                context_files = overrides["context_files"]
        except Exception:
            pass

    parts: list[str] = []
    for fname in context_files:
        fpath = path / fname
        if fpath.exists():
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                parts.append(f"=== {fname} ===\n{content}")
            except Exception:
                pass

    return "\n\n".join(parts)
