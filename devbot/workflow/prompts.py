"""Prompt builders for role-based project work."""

from __future__ import annotations

from typing import TYPE_CHECKING

from devbot.workflow.registry import load_role_registry, load_workflow_registry

if TYPE_CHECKING:
    from devbot.config.settings import Config, ProjectConfig
    from devbot.workflow.models import WorkflowRun


def build_project_profile_summary(project_name: str, project_cfg: "ProjectConfig") -> str:
    lines = [
        f"Project: {project_name}",
        f"Type: {project_cfg.type}",
    ]
    if project_cfg.description:
        lines.append(f"Description: {project_cfg.description}")
    if project_cfg.docs.agent_context:
        lines.append(f"Agent context docs: {', '.join(project_cfg.docs.agent_context)}")
    if project_cfg.docs.architecture:
        lines.append(f"Architecture docs: {', '.join(project_cfg.docs.architecture)}")
    if project_cfg.docs.product:
        lines.append(f"Product docs: {', '.join(project_cfg.docs.product)}")
    if project_cfg.commands.install:
        lines.append(f"Install command: {project_cfg.commands.install}")
    if project_cfg.commands.test:
        lines.append(f"Test command: {project_cfg.commands.test}")
    if project_cfg.commands.run:
        lines.append(f"Run command: {project_cfg.commands.run}")
    if project_cfg.auto_restart:
        lines.append("Auto restart: enabled")
    if project_cfg.commands.restart:
        lines.append(f"Restart command: {project_cfg.commands.restart}")
    if project_cfg.qa.smoke_commands:
        lines.append(f"QA smoke commands: {', '.join(project_cfg.qa.smoke_commands)}")
    if project_cfg.role_preferences:
        pairs = ", ".join(f"{k}={v}" for k, v in project_cfg.role_preferences.items())
        lines.append(f"Role preferences: {pairs}")
    return "\n".join(lines)


def _trim_block(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 16] + "\n...[truncated]"


def build_cli_task_prompt(
    task: str,
    project_name: str,
    project_cfg: "ProjectConfig",
    project_context: str = "",
    files: list[str] | None = None,
    run: "WorkflowRun | None" = None,
) -> str:
    parts = [
        "You are working inside DevBot's project workflow.",
        build_project_profile_summary(project_name, project_cfg),
    ]
    if run is not None:
        parts.append(f"Run directory: {run.run_dir}")
    if files:
        parts.append(f"Focus files: {', '.join(files)}")
    if project_context:
        parts.append("Project context:\n" + _trim_block(project_context, 12000))
    parts.append("Task:\n" + task)
    return "\n\n".join(parts)


def build_analysis_prompt(
    config: "Config",
    project_name: str,
    project_cfg: "ProjectConfig",
    goal: str,
    mode: str,
    role_name: str,
    workflow_name: str,
    file_bundle: str,
    selected_files: list[str],
    run: "WorkflowRun | None" = None,
) -> str:
    role_registry = load_role_registry(config)
    workflow_registry = load_workflow_registry(config)
    role_def = role_registry.get(role_name)
    workflow_def = workflow_registry.get(workflow_name)

    parts = [
        f"Act as the `{role_name}` role in DevBot's `{workflow_name}` workflow.",
        build_project_profile_summary(project_name, project_cfg),
        f"Mode: {mode}",
        f"Goal: {goal}",
    ]
    if role_def and role_def.purpose:
        parts.append(f"Role purpose: {role_def.purpose}")
    if workflow_def and workflow_def.stages:
        parts.append(f"Workflow stages: {', '.join(workflow_def.stages)}")
    if selected_files:
        parts.append(f"Selected files: {', '.join(selected_files)}")
    if run is not None:
        parts.append(f"Run directory: {run.run_dir}")
    parts.append(
        "Deliver a structured assessment with evidence from the files. If evidence is missing, say so explicitly."
    )
    parts.append(
        "Response format:\n"
        "1. Findings ordered by severity\n"
        "2. Workflow/design evaluation\n"
        "3. Recommended next steps"
    )
    if file_bundle:
        parts.append("Project files:\n" + _trim_block(file_bundle, 48000))
    return "\n\n".join(parts)
