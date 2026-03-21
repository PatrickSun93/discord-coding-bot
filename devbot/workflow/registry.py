"""Load role and workflow registries from packaged defaults plus config overrides."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from devbot.workflow.models import RoleDefinition, WorkflowDefinition

if TYPE_CHECKING:
    from devbot.config.settings import Config


_DEFAULT_ROLES_PATH = Path(__file__).with_name("default_roles.yaml")
_DEFAULT_WORKFLOWS_PATH = Path(__file__).with_name("default_workflows.yaml")


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _merge_mappings(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {**base}
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def load_role_registry(config: "Config | None" = None) -> dict[str, RoleDefinition]:
    raw = _load_yaml(_DEFAULT_ROLES_PATH)
    if config is not None:
        raw = _merge_mappings(raw, config.team_roles)
    return {
        name: RoleDefinition.from_dict(name, data or {})
        for name, data in raw.items()
    }


def load_workflow_registry(config: "Config | None" = None) -> dict[str, WorkflowDefinition]:
    raw = _load_yaml(_DEFAULT_WORKFLOWS_PATH)
    if config is not None:
        raw = _merge_mappings(raw, config.workflows)
    return {
        name: WorkflowDefinition.from_dict(name, data or {})
        for name, data in raw.items()
    }


def _role_labels(role_name: str) -> list[str]:
    labels = {role_name}
    if role_name == "planner":
        labels.update({"reviewer", "analyst"})
    if role_name == "qa":
        labels.update({"tester", "reviewer"})
    if role_name == "release":
        labels.update({"reviewer", "coder"})
    if role_name == "investigator":
        labels.update({"coder", "reviewer"})
    return list(labels)


def select_cli_for_role(
    role_name: str,
    config: "Config",
    project_name: str = "",
    preferred_cli: str = "",
) -> str:
    project_cfg = config.projects.get(project_name) if project_name else None
    role_registry = load_role_registry(config)
    role_def = role_registry.get(role_name)

    candidates: list[str] = []
    if preferred_cli:
        candidates.append(preferred_cli)
    if project_cfg:
        project_preference = project_cfg.role_preferences.get(role_name, "")
        if project_preference:
            candidates.append(project_preference)
        if role_name == "reviewer" and project_cfg.analysis.preferred_reviewer_cli:
            candidates.append(project_cfg.analysis.preferred_reviewer_cli)
    if role_def:
        candidates.extend(role_def.preferred_clis)

    for cli_name in candidates:
        cli_cfg = getattr(config.cli, cli_name, None)
        if cli_cfg and cli_cfg.enabled:
            return cli_name

    labels = set(_role_labels(role_name))
    for cli_name in ("claude_code", "codex", "gemini_cli", "qwen_cli"):
        cli_cfg = getattr(config.cli, cli_name, None)
        if cli_cfg and cli_cfg.enabled and labels.intersection(cli_cfg.roles):
            return cli_name

    return "claude_code"
