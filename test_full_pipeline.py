"""Lightweight integration checks for the workflow foundation."""

from __future__ import annotations

import shutil
from pathlib import Path

from devbot.config.settings import ProjectConfig, load_config
from devbot.context.files import build_file_bundle, select_analysis_files
from devbot.context.loader import load_project_context
from devbot.llm.tools_schema import build_system_prompt
from devbot.workflow.prompts import build_analysis_prompt, build_cli_task_prompt
from devbot.workflow.registry import load_role_registry, load_workflow_registry
from devbot.workflow.store import start_workflow_run, write_artifact

cfg = load_config()
roles = load_role_registry(cfg)
workflows = load_workflow_registry(cfg)

assert "planner" in roles
assert "feature_delivery" in workflows
print("Registry load OK")

tmp_root = Path(".tmp-pipeline")
tmp_project = tmp_root / "project"
shutil.rmtree(tmp_root, ignore_errors=True)
tmp_project.mkdir(parents=True, exist_ok=True)

try:
    (tmp_project / "CLAUDE.md").write_text("# Context\nUse snake_case.", encoding="utf-8")
    (tmp_project / "AGENTS.md").write_text("# Agents\nBe concise.", encoding="utf-8")
    (tmp_project / "workflow-design.md").write_text("# Workflow\nDesign notes.", encoding="utf-8")

    project_cfg = ProjectConfig(path=tmp_project)
    context = load_project_context(str(tmp_project), cfg, "")
    assert "Use snake_case" in context
    print("Context loading OK")

    files = select_analysis_files(
        project_path=str(tmp_project),
        project_cfg=project_cfg,
        goal="evaluate current workflow design",
        file_hints=["workflow-design.md"],
    )
    bundle, included = build_file_bundle(str(tmp_project), files)
    assert "workflow-design.md" in included
    print(f"Analysis file selection OK — {included}")

    run = start_workflow_run(
        project_path=str(tmp_project),
        project_name="tmp-project",
        workflow="analysis",
        role="reviewer",
        goal="evaluate current workflow design",
    )
    write_artifact(run, "brief.md", "# Brief")

    analysis_prompt = build_analysis_prompt(
        config=cfg,
        project_name="tmp-project",
        project_cfg=project_cfg,
        goal="evaluate current workflow design",
        mode="evaluate",
        role_name="reviewer",
        workflow_name="analysis",
        file_bundle=bundle,
        selected_files=included,
        run=run,
    )
    assert "Selected files" in analysis_prompt
    assert "Design notes" in analysis_prompt
    print("Analysis prompt OK")

    cli_prompt = build_cli_task_prompt(
        task="add tests",
        project_name="tmp-project",
        project_cfg=project_cfg,
        project_context=context,
        files=["tests/test_sample.py"],
        run=run,
    )
    assert "Focus files" in cli_prompt
    assert "Task:" in cli_prompt
    print("CLI prompt OK")

    system_prompt = build_system_prompt(cfg)
    assert "WORKFLOWS" in system_prompt
    assert "analyze_project" in system_prompt
    print("System prompt OK")
finally:
    shutil.rmtree(tmp_root, ignore_errors=True)

print("All lightweight integration checks passed.")
