"""Project file discovery and bounded file loading."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from devbot.config.settings import ProjectConfig


_GLOB_CHARS = set("*?[")
_DEFAULT_DOC_GLOBS = [
    "README.md",
    "CLAUDE.md",
    "AGENTS.md",
    "GEMINI.md",
    "ARCHITECTURE.md",
    "*architecture*.md",
    "*design*.md",
    "*workflow*.md",
    "docs/**/*.md",
]


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in paths:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def _load_devbot_overrides(project_path: str) -> dict:
    override_path = Path(project_path) / ".devbot.yaml"
    if not override_path.is_file():
        return {}
    try:
        return yaml.safe_load(override_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def resolve_project_files(
    project_path: str,
    patterns: list[str],
    max_files: int = 12,
) -> list[Path]:
    root = Path(project_path)
    matches: list[Path] = []
    for pattern in patterns:
        if not pattern:
            continue
        candidate = Path(pattern)
        if candidate.is_absolute():
            if candidate.is_file() and _is_within(root, candidate):
                matches.append(candidate)
        elif any(ch in pattern for ch in _GLOB_CHARS):
            for path in sorted(root.glob(pattern)):
                if path.is_file():
                    matches.append(path)
        else:
            path = root / pattern
            if path.is_file():
                matches.append(path)
        if len(matches) >= max_files:
            break
    return _dedupe_paths(matches)[:max_files]


def select_analysis_files(
    project_path: str,
    project_cfg: "ProjectConfig",
    goal: str,
    file_hints: list[str] | None = None,
    max_files: int = 8,
) -> list[Path]:
    overrides = _load_devbot_overrides(project_path)
    analysis_overrides = overrides.get("analysis", {}) if isinstance(overrides, dict) else {}

    explicit = resolve_project_files(project_path, file_hints or [], max_files=max_files)
    if explicit:
        return explicit

    goal_lower = goal.lower()
    patterns: list[str] = []
    patterns.extend(
        [str(v) for v in analysis_overrides.get("entry_files", []) if str(v).strip()]
        or project_cfg.analysis.entry_files
    )

    if any(word in goal_lower for word in ("workflow", "architecture", "design", "evaluate", "analysis")):
        patterns.extend(project_cfg.docs.architecture)
    if any(word in goal_lower for word in ("bug", "qa", "test", "verify")):
        patterns.extend(project_cfg.docs.product)

    patterns.extend(project_cfg.docs.agent_context)
    patterns.extend(project_cfg.docs.product)
    patterns.extend(project_cfg.context_files)
    patterns.extend(
        [str(v) for v in analysis_overrides.get("doc_globs", []) if str(v).strip()]
        or project_cfg.analysis.doc_globs
    )
    patterns.extend(_DEFAULT_DOC_GLOBS)

    return resolve_project_files(project_path, patterns, max_files=max_files)


def build_file_bundle(
    project_path: str,
    files: list[Path],
    per_file_chars: int = 12000,
    max_total_chars: int = 48000,
) -> tuple[str, list[str]]:
    root = Path(project_path)
    sections: list[str] = []
    included: list[str] = []
    remaining = max_total_chars

    for path in files:
        rel = path.relative_to(root).as_posix() if _is_within(root, path) else str(path)
        text = path.read_text(encoding="utf-8", errors="replace")
        if len(text) > per_file_chars:
            text = text[: per_file_chars - 16] + "\n...[truncated]"

        header = f"=== {rel} ===\n"
        block = header + text
        if len(block) > remaining:
            if remaining <= len(header) + 16:
                break
            text = text[: remaining - len(header) - 16] + "\n...[truncated]"
            block = header + text

        sections.append(block)
        included.append(rel)
        remaining -= len(block) + 2
        if remaining <= 0:
            break

    return "\n\n".join(sections), included
