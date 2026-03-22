"""Quick smoke test — run with: conda run -n devbot python smoke_test.py"""

from __future__ import annotations

import shutil
from pathlib import Path

from devbot.config.settings import _default_config_path
from devbot.context.files import build_file_bundle, resolve_project_files, select_analysis_files
from devbot.executor.adapters.claude_code import ClaudeCodeAdapter
from devbot.executor.adapters.codex import CodexAdapter
from devbot.executor.adapters.gemini_cli import GeminiCLIAdapter
from devbot.executor.adapters.qwen_cli import QwenCLIAdapter
from devbot.executor.shell.blocklist import is_command_blocked
from devbot.executor.shell.platform import detect_platform, windows_path_to_wsl
from devbot.llm.tools_schema import ANTHROPIC_TOOLS, TOOLS, build_system_prompt
from devbot.context.loader import load_project_context
from devbot.context.project import resolve_project
from devbot.config.settings import load_config
from devbot.executor.auto_restart import (
    capture_project_snapshot,
    detect_restart_relevant_changes,
    resolve_auto_restart_plan,
)
from devbot.todo import TodoItem, add_todo_item, parse_todo_file, prepare_todo_item
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

print("All imports OK")
print("Default config path:", _default_config_path())

# Adapter smoke tests — [cmd] + base_args + autonomy_args + extra_args + [task]
adapter = ClaudeCodeAdapter()
cmd = adapter.build_command("add tests", "/tmp/proj")
assert Path(cmd[0]).name.lower().startswith("claude")
assert "-p" in cmd
assert cmd[cmd.index("-p") + 1] == "add tests"
assert "--output-format" in cmd
assert "stream-json" in cmd
assert "--dangerously-skip-permissions" in cmd
print(f"ClaudeCodeAdapter.build_command OK: {cmd}")

adapter_codex = CodexAdapter()
cmd_codex = adapter_codex.build_command("fix bug", "/tmp/proj")
assert Path(cmd_codex[0]).name.lower().startswith("codex")
assert "exec" in cmd_codex
assert "--json" in cmd_codex
assert "--full-auto" in cmd_codex
assert "--skip-git-repo-check" in cmd_codex
assert cmd_codex[-1] == "fix bug"
print(f"CodexAdapter.build_command OK: {cmd_codex}")

adapter_q = QwenCLIAdapter()
cmd_q = adapter_q.build_command("write docs", "/tmp/proj")
assert Path(cmd_q[0]).name.lower().startswith("qwen")
assert "--yolo" in cmd_q
assert cmd_q[cmd_q.index("-p") + 1] == "write docs"
print(f"QwenCLIAdapter.build_command OK: {cmd_q}")

adapter_g = GeminiCLIAdapter()
cmd_g = adapter_g.build_command("review code", "/tmp/proj")
assert Path(cmd_g[0]).name.lower().startswith("gemini")
assert "--yolo" in cmd_g
assert cmd_g[cmd_g.index("-p") + 1] == "review code"
print(f"GeminiCLIAdapter.build_command OK: {cmd_g}")

# Tool schema sanity
assert len(TOOLS) == 9, f"Expected 9 tools, got {len(TOOLS)}"
tool_names = {t["function"]["name"] for t in TOOLS}
assert tool_names == {
    "run_cli",
    "run_pipeline",
    "run_shell",
    "read_context",
    "read_files",
    "analyze_project",
    "todo_add",
    "ask_clarification",
    "list_projects",
}, tool_names
assert len(ANTHROPIC_TOOLS) == 9
print(f"Tool schema OK — tools: {tool_names}")

cfg = load_config()

# Role and workflow registries
roles = load_role_registry(cfg)
workflows = load_workflow_registry(cfg)
assert "reviewer" in roles
assert "analysis" in workflows
selected_cli = select_cli_for_role("reviewer", cfg)
assert selected_cli in {"claude_code", "codex", "gemini_cli", "qwen_cli"}
print(f"Workflow registry OK — roles={list(roles)[:3]} workflows={list(workflows)[:3]}")

# Dynamic system prompt
prompt = build_system_prompt(cfg)
assert "analyze_project" in prompt
assert "TEAM ROLES" in prompt
assert "WORKFLOWS" in prompt
print("build_system_prompt OK")

# Blocklist
blocked, reason = is_command_blocked("rm -rf /")
assert blocked, "rm should be blocked"
blocked2, _ = is_command_blocked("ls -la")
assert not blocked2, "ls should not be blocked"
blocked3, _ = is_command_blocked("shutdown -h now")
assert blocked3, "shutdown should be blocked"
print("blocklist OK")

# WSL path conversion
wsl_path = windows_path_to_wsl("C:\\Users\\peido\\project")
assert wsl_path == "/mnt/c/Users/peido/project", wsl_path
print(f"WSL path conversion OK: {wsl_path}")

# Platform detection
info = detect_platform()
assert info.os_name in ("Windows", "Darwin", "Linux")
print(f"Platform detection OK: os={info.os_name} shell={info.default_shell} shells={info.available_shells}")

tmp_root = Path(".tmp-smoke")
tmp_root.mkdir(exist_ok=True)
tmp_dir = tmp_root / "project"
shutil.rmtree(tmp_dir, ignore_errors=True)
tmp_dir.mkdir(parents=True, exist_ok=True)

try:
    # Project resolve — path-based
    class FakeConfig:
        projects = {}

    path, name = resolve_project(str(tmp_dir), FakeConfig())
    assert path == str(tmp_dir)
    print(f"resolve_project (path) OK — {name}")

    # Context + analysis file loading
    (tmp_dir / "CLAUDE.md").write_text("# Context\nFollow conventions.", encoding="utf-8")
    (tmp_dir / "README.md").write_text("# Product\nOverview.", encoding="utf-8")
    (tmp_dir / "workflow-design.md").write_text("# Workflow\nCurrent design notes.", encoding="utf-8")

    ctx = load_project_context(str(tmp_dir), cfg, "")
    assert "Follow conventions" in ctx

    matches = resolve_project_files(str(tmp_dir), ["*.md"])
    assert len(matches) >= 3

    project_cfg = next(iter(cfg.projects.values())) if cfg.projects else None
    if project_cfg is None:
        from devbot.config.settings import ProjectConfig

        project_cfg = ProjectConfig(path=tmp_dir)

    analysis_files = select_analysis_files(
        project_path=str(tmp_dir),
        project_cfg=project_cfg,
        goal="evaluate the workflow design",
        file_hints=["workflow-design.md"],
    )
    bundle, included = build_file_bundle(str(tmp_dir), analysis_files)
    assert "workflow-design.md" in included
    assert "Current design notes" in bundle
    print(f"File discovery OK — selected={included}")

    todo_path = tmp_root / "todos.md"
    todo_item = TodoItem(
        item_id="smoke",
        priority=1,
        cli="claude",
        project=str(tmp_dir),
        task="Review the workflow design",
    )
    add_todo_item(todo_path, todo_item)
    parsed_items = parse_todo_file(todo_path)
    assert len(parsed_items) == 1
    prepared_item, issue = prepare_todo_item(parsed_items[0], cfg)
    assert issue is None
    assert prepared_item is not None
    print(f"Todo parsing OK — {prepared_item.item.cli} -> {prepared_item.project_name}")

    from devbot.config.settings import ProjectCommandsConfig, ProjectConfig

    restart_cfg = ProjectConfig(
        path=tmp_dir,
        auto_restart=True,
        commands=ProjectCommandsConfig(restart="echo restart", restart_shell="cmd"),
    )
    before = capture_project_snapshot(str(tmp_dir))
    (tmp_dir / "app.py").write_text("print('changed')\n", encoding="utf-8")
    after = capture_project_snapshot(str(tmp_dir))
    restart_changes = detect_restart_relevant_changes(before, after)
    assert "app.py" in restart_changes
    plan, _ = resolve_auto_restart_plan(cfg, restart_cfg, "tmp-proj")
    assert plan is not None
    print(f"Auto restart planning OK — changes={restart_changes[:2]}")

    run = start_workflow_run(
        project_path=str(tmp_dir),
        project_name="tmp-proj",
        workflow="analysis",
        role="reviewer",
        goal="evaluate workflow design",
    )
    artifact = write_artifact(run, "brief.md", "# brief")
    append_workflow_event(run, stage="reviewer", status="completed", message="Smoke event")
    set_workflow_status(run, status="succeeded", summary="smoke ok")
    events = read_workflow_events(run)
    assert artifact.exists()
    assert events
    print(f"Workflow store OK — run={run.run_id}")
finally:
    shutil.rmtree(tmp_root, ignore_errors=True)

print("\nAll checks passed.")
