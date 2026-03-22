"""Workflow foundation for role-based project work."""

from devbot.workflow.models import RoleDefinition, WorkflowDefinition, WorkflowEvent, WorkflowRun
from devbot.workflow.pipeline import FeatureDeliveryPipeline, PipelineExecutionResult
from devbot.workflow.registry import (
    load_role_registry,
    load_workflow_registry,
    select_cli_for_role,
)
from devbot.workflow.store import (
    append_workflow_event,
    read_workflow_events,
    set_workflow_status,
    start_workflow_run,
    write_artifact,
)

__all__ = [
    "RoleDefinition",
    "WorkflowDefinition",
    "WorkflowEvent",
    "WorkflowRun",
    "FeatureDeliveryPipeline",
    "PipelineExecutionResult",
    "load_role_registry",
    "load_workflow_registry",
    "select_cli_for_role",
    "append_workflow_event",
    "read_workflow_events",
    "set_workflow_status",
    "start_workflow_run",
    "write_artifact",
]
