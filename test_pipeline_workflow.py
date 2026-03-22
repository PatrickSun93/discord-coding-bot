"""Scenario tests for the feature-delivery pipeline and durable workflow logs."""

from __future__ import annotations

import json
import platform
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from devbot.bot.client import DevBotClient
from devbot.bot.formatter import format_combined_status
from devbot.executor.manager import TaskResult
from devbot.executor.shell import run_shell
from devbot.executor.shell.platform import detect_platform
from devbot.todo.models import PreparedTodoItem, TodoItem, TodoQueueStatus
from devbot.workflow.pipeline import FeatureDeliveryPipeline
from devbot.workflow.store import append_workflow_event, start_workflow_run
from test_support import FakeChannel, build_config


class _FakeTaskManager:
    def __init__(self, project_path: Path, review_verdicts: list[str] | None = None, cancel_after_coder: bool = False):
        self.project_path = project_path
        self.review_verdicts = list(review_verdicts or ["APPROVED"])
        self.cancel_after_coder = cancel_after_coder
        self.coder_runs = 0
        self.plan_runs = 0
        self.review_runs = 0
        self.qa_runs = 0
        self.cancel_flag = False

    def current_cli_info(self, _cli_name: str):
        return None

    async def execute(
        self,
        adapter,
        task: str,
        project_path: str,
        project_name: str,
        channel,
        workflow: str = "",
        run_id: str = "",
        log_path: str = "",
    ) -> TaskResult:
        assert project_path == str(self.project_path)
        assert project_name == "alpha"
        assert workflow in {"", "feature_delivery"}
        if run_id:
            assert log_path
        await channel.send(f"[fake:{adapter.name}]")

        if "Create a concise execution plan" in task:
            self.plan_runs += 1
            return TaskResult(returncode=0, transcript="1. Scope\n2. Steps\n3. Risks\n4. Validation", duration=0.01)

        if "Review the changes below" in task:
            self.review_runs += 1
            verdict = self.review_verdicts.pop(0) if self.review_verdicts else "APPROVED"
            return TaskResult(
                returncode=0,
                transcript=f"Review notes for cycle {self.review_runs}\nVERDICT: {verdict}",
                duration=0.01,
            )

        if "Analyze this qa failure" in task or "Analyze this lint failure" in task:
            self.qa_runs += 1
            return TaskResult(returncode=0, transcript="Fix the failing assertion and rerun the command.", duration=0.01)

        self.coder_runs += 1
        app_path = self.project_path / "app.py"
        app_path.write_text(
            app_path.read_text(encoding="utf-8") + f"print('cycle {self.coder_runs}')\n",
            encoding="utf-8",
        )
        if self.cancel_after_coder:
            self.cancel_flag = True
        return TaskResult(returncode=0, transcript=f"Implemented cycle {self.coder_runs}", duration=0.01)


class PipelineWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.repo = self.root / "repo"
        self.repo.mkdir(parents=True, exist_ok=True)
        self.shell = "cmd" if platform.system() == "Windows" else "bash"
        self.platform = detect_platform(preferred=self.shell)
        self.channel = FakeChannel()

    async def asyncSetUp(self) -> None:
        await self._init_repo()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    async def _run_git(self, command: str) -> str:
        result = await run_shell(
            command=command,
            shell=self.shell,
            working_dir=str(self.repo),
            timeout=30,
            platform_info=self.platform,
        )
        self.assertEqual(result.returncode, 0, msg=f"{command}\n{result.output}")
        return result.output

    async def _init_repo(self) -> None:
        await self._run_git("git init")
        await self._run_git("git checkout -b main")
        await self._run_git('git config user.email "devbot@example.com"')
        await self._run_git('git config user.name "DevBot Test"')
        (self.repo / "README.md").write_text("# Pipeline test\n", encoding="utf-8")
        (self.repo / "app.py").write_text("print('base')\n", encoding="utf-8")
        await self._run_git("git add -A")
        await self._run_git('git commit -m "initial"')

    def _build_pipeline(self, *, review_verdicts: list[str] | None = None, cancel_after_coder: bool = False):
        config = build_config(
            self.root / "cfg",
            project_specs={
                "alpha": {
                    "path": self.repo,
                    "coder": "codex",
                    "reviewers": ["gemini_cli"],
                    "tester": "gemini_cli",
                    "test_command": "git status --short",
                    "plan_threshold": "always",
                    "max_cycles": 3,
                }
            },
        )
        task_manager = _FakeTaskManager(
            self.repo,
            review_verdicts=review_verdicts,
            cancel_after_coder=cancel_after_coder,
        )
        pipeline = FeatureDeliveryPipeline(
            config=config,
            task_manager=task_manager,
            channel=self.channel,
            platform_info=self.platform,
            project_name="alpha",
            project_path=str(self.repo),
            project_cfg=config.projects["alpha"],
            task="Add a small pipeline test feature",
            source="test",
            cancel_requested=lambda: task_manager.cancel_flag,
        )
        return config, task_manager, pipeline

    async def test_pipeline_happy_path_writes_logs_and_artifacts(self) -> None:
        _config, task_manager, pipeline = self._build_pipeline()

        result = await pipeline.run_pipeline()

        self.assertTrue(result.success, result.summary)
        self.assertEqual(task_manager.plan_runs, 1)
        self.assertEqual(task_manager.coder_runs, 1)
        self.assertEqual(task_manager.review_runs, 1)

        run_json = json.loads((pipeline.run.run_dir / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(run_json["status"], "succeeded")
        self.assertTrue((pipeline.run.run_dir / "timeline.md").exists())
        self.assertTrue((pipeline.run.run_dir / "events.jsonl").exists())
        self.assertTrue((pipeline.run.run_dir / "plan.md").exists())
        self.assertTrue((pipeline.run.run_dir / "release-summary.md").exists())

        timeline = (pipeline.run.run_dir / "timeline.md").read_text(encoding="utf-8")
        self.assertIn("[planner]", timeline)
        self.assertIn("[coder]", timeline)
        self.assertIn("[review]", timeline)
        self.assertIn("[qa]", timeline)
        self.assertIn("[release]", timeline)
        self.assertIn("[push]", timeline)

        current_branch = await self._run_git("git rev-parse --abbrev-ref HEAD")
        self.assertTrue(current_branch.strip().startswith("feature/"))
        log_output = await self._run_git("git log --oneline -1")
        self.assertIn("devbot: cycle 1", log_output)
        self.assertIn("cycle 1", (self.repo / "app.py").read_text(encoding="utf-8"))

    async def test_pipeline_loops_when_review_requests_changes(self) -> None:
        _config, task_manager, pipeline = self._build_pipeline(
            review_verdicts=["CHANGES_REQUESTED", "APPROVED"],
        )

        result = await pipeline.run_pipeline()

        self.assertTrue(result.success, result.summary)
        self.assertEqual(task_manager.coder_runs, 2)
        self.assertEqual(task_manager.review_runs, 2)

        timeline = (pipeline.run.run_dir / "timeline.md").read_text(encoding="utf-8")
        self.assertIn("Cycle 1 started", timeline)
        self.assertIn("Cycle 2 started", timeline)

    async def test_pipeline_cancel_stops_between_steps(self) -> None:
        _config, task_manager, pipeline = self._build_pipeline(cancel_after_coder=True)

        result = await pipeline.run_pipeline()

        self.assertFalse(result.success)
        self.assertIn("cancelled", result.summary.lower())
        run_json = json.loads((pipeline.run.run_dir / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(run_json["status"], "cancelled")
        self.assertEqual(task_manager.coder_runs, 1)
        self.assertEqual(task_manager.review_runs, 0)


class ClientTodoPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_todo_pipeline_items_delegate_to_feature_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = build_config(root)
            client = DevBotClient(config)
            try:
                prepared = PreparedTodoItem(
                    item=TodoItem(item_id="1", priority=1, cli="pipeline", project="alpha", task="Ship it"),
                    cli_key="claude_code",
                    project_path=str(config.projects["alpha"].path),
                    project_name="alpha",
                    mode="pipeline",
                )
                client._run_feature_pipeline = AsyncMock(
                    return_value=SimpleNamespace(
                        success=True,
                        duration=1.25,
                        summary="pipeline ok",
                    )
                )

                result = await client._run_todo_item(prepared, FakeChannel())

                client._run_feature_pipeline.assert_awaited_once()
                self.assertEqual(result.status, "success")
                self.assertEqual(result.duration, 1.25)
                self.assertEqual(result.summary, "pipeline ok")
            finally:
                await client.close()

    async def test_active_pipeline_status_surfaces_logs_in_status_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = build_config(root)
            client = DevBotClient(config)
            try:
                run = start_workflow_run(
                    project_path=str(config.projects["alpha"].path),
                    project_name="alpha",
                    workflow="feature_delivery",
                    role="planner",
                    goal="Ship a feature",
                )
                append_workflow_event(
                    run,
                    stage="review",
                    status="started",
                    message="Review step is active.",
                )
                client._active_pipeline_runs["alpha"] = run

                message = format_combined_status(
                    {},
                    TodoQueueStatus(is_running=False),
                    client.active_pipeline_statuses(),
                )

                self.assertIn("Feature Pipelines", message)
                self.assertIn("Review step is active.", message)
                self.assertIn(str(run.run_dir / "timeline.md"), message)
            finally:
                await client.close()
