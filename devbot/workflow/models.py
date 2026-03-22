"""Typed workflow and role metadata."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class RoleDefinition:
    name: str
    purpose: str = ""
    capabilities: list[str] = field(default_factory=list)
    preferred_clis: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    allowed_tools: list[str] = field(default_factory=list)
    success_to: list[str] = field(default_factory=list)
    failure_to: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "RoleDefinition":
        return cls(
            name=name,
            purpose=str(data.get("purpose", "")),
            capabilities=[str(v) for v in data.get("capabilities", [])],
            preferred_clis=[str(v) for v in data.get("preferred_clis", [])],
            inputs=[str(v) for v in data.get("inputs", [])],
            outputs=[str(v) for v in data.get("outputs", [])],
            allowed_tools=[str(v) for v in data.get("allowed_tools", [])],
            success_to=[str(v) for v in data.get("success_to", [])],
            failure_to=[str(v) for v in data.get("failure_to", [])],
        )


@dataclass
class WorkflowDefinition:
    name: str
    description: str = ""
    stages: list[str] = field(default_factory=list)
    default_entry_role: str = ""

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "WorkflowDefinition":
        stages = [str(v) for v in data.get("stages", [])]
        return cls(
            name=name,
            description=str(data.get("description", "")),
            stages=stages,
            default_entry_role=str(data.get("default_entry_role", "")) or (stages[0] if stages else ""),
        )


@dataclass
class WorkflowRun:
    run_id: str
    workflow: str
    role: str
    goal: str
    project_name: str
    project_path: Path
    run_dir: Path


@dataclass
class ActiveWorkflowStatus:
    project_name: str
    workflow: str
    run_id: str
    log_path: Path
    stage: str = ""
    status: str = ""
    message: str = ""


@dataclass
class WorkflowEvent:
    timestamp: str
    stage: str
    status: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
