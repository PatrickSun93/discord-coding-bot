"""Persist workflow run metadata and artifacts inside each project."""

from __future__ import annotations

import json
import re
import time
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
        "metadata": metadata or {},
    }
    (run_dir / "run.json").write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )

    return WorkflowRun(
        run_id=run_id,
        workflow=workflow,
        role=role,
        goal=goal,
        project_name=project_name,
        project_path=Path(project_path),
        run_dir=run_dir,
    )


def write_artifact(run: WorkflowRun, filename: str, content: str) -> Path:
    path = run.run_dir / filename
    path.write_text(content, encoding="utf-8")
    return path
