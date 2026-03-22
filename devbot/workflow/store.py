"""Persist workflow run metadata and artifacts inside each project."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from devbot.workflow.models import WorkflowRun


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip()).strip("-").lower()
    return slug[:48] or "run"


def start_workflow_run(
    project_path: str,
    project_name: str,
    workflow: str,
    role: str,
    goal: str,
    metadata: dict[str, Any] | None = None,
) -> WorkflowRun:
    root = Path(project_path) / ".devbot" / "runs" / workflow
    root.mkdir(parents=True, exist_ok=True)

    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{_slugify(goal)}"
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    payload = {
        "run_id": run_id,
        "workflow": workflow,
        "role": role,
        "goal": goal,
        "project_name": project_name,
        "project_path": str(project_path),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "running",
        "metadata": metadata or {},
    }
    _write_run_payload(run_dir, payload)

    run = WorkflowRun(
        run_id=run_id,
        workflow=workflow,
        role=role,
        goal=goal,
        project_name=project_name,
        project_path=Path(project_path),
        run_dir=run_dir,
    )
    append_workflow_event(
        run,
        stage="workflow",
        status="started",
        message="Workflow run started.",
        details={"role": role},
    )
    return run


def write_artifact(run: WorkflowRun, filename: str, content: str) -> Path:
    path = run.run_dir / filename
    path.write_text(content, encoding="utf-8")
    return path


def append_workflow_event(
    run: WorkflowRun,
    *,
    stage: str,
    status: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> Path:
    event = {
        "timestamp": _utc_now(),
        "stage": stage,
        "status": status,
        "message": message,
        "details": details or {},
    }
    path = run.run_dir / "events.jsonl"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, sort_keys=True) + "\n")

    timeline = run.run_dir / "timeline.md"
    detail_text = _format_event_details(event["details"])
    with timeline.open("a", encoding="utf-8") as fh:
        fh.write(
            f"- {event['timestamp']} [{stage}] **{status.upper()}** {message}{detail_text}\n"
        )
    return path


def set_workflow_status(
    run: WorkflowRun,
    *,
    status: str,
    summary: str = "",
    extra: dict[str, Any] | None = None,
) -> Path:
    path = run.run_dir / "run.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["status"] = status
    payload["updated_at"] = _utc_now()
    if summary:
        payload["summary"] = summary
    if extra:
        payload.setdefault("result", {}).update(extra)
    _write_run_payload(run.run_dir, payload)
    return path


def read_workflow_events(run: WorkflowRun) -> list[dict[str, Any]]:
    path = run.run_dir / "events.jsonl"
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


def _write_run_payload(run_dir: Path, payload: dict[str, Any]) -> None:
    (run_dir / "run.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _format_event_details(details: dict[str, Any]) -> str:
    if not details:
        return ""
    parts = [f"{key}={value}" for key, value in details.items()]
    return " (" + ", ".join(parts) + ")"
