"""Concrete feature-delivery pipeline with durable step logging."""

from __future__ import annotations

import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from devbot.context.loader import load_project_context
from devbot.executor.adapters.factory import build_adapter
from devbot.executor.shell import run_shell
from devbot.workflow.prompts import build_cli_task_prompt, build_project_profile_summary
from devbot.workflow.registry import select_cli_for_role
from devbot.workflow.store import (
    append_workflow_event,
    set_workflow_status,
    start_workflow_run,
    write_artifact,
)

if TYPE_CHECKING:
    from devbot.config.settings import Config, PipelineConfig, ProjectConfig
    from devbot.executor.manager import TaskManager, TaskResult
    from devbot.executor.shell.platform import PlatformInfo
    from devbot.workflow.models import WorkflowRun


@dataclass
class PipelineExecutionResult:
    success: bool
    run: "WorkflowRun"
    branch_name: str = ""
    cycle: int = 0
    duration: float = 0.0
    summary: str = ""
    push_status: str = ""
    pr_status: str = ""
    notes: list[str] = field(default_factory=list)


class FeatureDeliveryPipeline:
    def __init__(
        self,
        *,
        config: "Config",
        task_manager: "TaskManager",
        channel,
        platform_info: "PlatformInfo",
        project_name: str,
        project_path: str,
        project_cfg: "ProjectConfig",
        task: str,
        source: str,
        cancel_requested=None,
    ) -> None:
        self.config = config
        self.task_manager = task_manager
        self.channel = channel
        self.platform_info = platform_info
        self.project_name = project_name
        self.project_path = project_path
        self.project_cfg = project_cfg
        self.task = task.strip()
        self.source = source
        self.cancel_requested = cancel_requested
        self.pipeline_cfg = _resolve_pipeline_config(config, project_name, project_cfg)
        self.run = start_workflow_run(
            project_path=project_path,
            project_name=project_name,
            workflow="feature_delivery",
            role="planner",
            goal=self.task,
            metadata={"source": source, "pipeline": _pipeline_metadata(self.pipeline_cfg)},
        )
        self.branch_name = ""
        self.cycle = 0
        self._feedback = ""
        self._plan_text = ""
        self._review_reports: list[str] = []
        self._qa_reports: list[str] = []

    async def run_pipeline(self) -> PipelineExecutionResult:
        append_workflow_event(
            self.run,
            stage="workflow",
            status="info",
            message="Feature delivery pipeline started.",
            details={"source": self.source},
        )
        await self.channel.send(
            f"🚀 Starting feature pipeline on `{self.project_name}`.\n"
            f"Run: `{self.run.run_id}`\n"
            f"Logs: `{self.run.run_dir / 'timeline.md'}`"
        )
        started = time.monotonic()

        try:
            self._ensure_local_git_exclude()
            self.branch_name = await self._create_branch()
            write_artifact(self.run, "branch.txt", self.branch_name + "\n")

            self._plan_text = await self._maybe_create_plan()

            for cycle in range(1, self.pipeline_cfg.max_cycles + 1):
                self._ensure_not_cancelled()
                self.cycle = cycle
                append_workflow_event(
                    self.run,
                    stage="cycle",
                    status="started",
                    message=f"Cycle {cycle} started.",
                    details={"cycle": cycle},
                )
                await self.channel.send(
                    f"🔄 Pipeline cycle `{cycle}/{self.pipeline_cfg.max_cycles}` on `{self.project_name}`."
                )

                await self._run_coder()

                self._ensure_not_cancelled()
                lint_ok = await self._run_lint()
                if not lint_ok:
                    append_workflow_event(
                        self.run,
                        stage="cycle",
                        status="info",
                        message="Looping back to coder after lint feedback.",
                        details={"cycle": cycle},
                    )
                    continue

                await self._commit()

                self._ensure_not_cancelled()
                review_ok = await self._run_review()
                if not review_ok:
                    append_workflow_event(
                        self.run,
                        stage="cycle",
                        status="info",
                        message="Looping back to coder after review feedback.",
                        details={"cycle": cycle},
                    )
                    continue

                self._ensure_not_cancelled()
                tests_ok = await self._run_tests()
                if not tests_ok:
                    append_workflow_event(
                        self.run,
                        stage="cycle",
                        status="info",
                        message="Looping back to coder after QA feedback.",
                        details={"cycle": cycle},
                    )
                    continue

                self._ensure_not_cancelled()
                push_status, pr_status = await self._release()
                summary = (
                    f"Pipeline completed on branch `{self.branch_name}` after {cycle} cycle"
                    f"{'s' if cycle != 1 else ''}."
                )
                set_workflow_status(
                    self.run,
                    status="succeeded",
                    summary=summary,
                    extra={
                        "branch_name": self.branch_name,
                        "cycles": cycle,
                        "push_status": push_status,
                        "pr_status": pr_status,
                    },
                )
                append_workflow_event(
                    self.run,
                    stage="workflow",
                    status="completed",
                    message=summary,
                    details={"branch": self.branch_name, "cycles": cycle},
                )
                await self.channel.send(f"✅ {summary}")
                return PipelineExecutionResult(
                    success=True,
                    run=self.run,
                    branch_name=self.branch_name,
                    cycle=cycle,
                    duration=time.monotonic() - started,
                    summary=summary,
                    push_status=push_status,
                    pr_status=pr_status,
                    notes=[push_status, pr_status],
                )

            summary = (
                f"Pipeline stopped after {self.pipeline_cfg.max_cycles} cycles on "
                f"`{self.branch_name}` without reaching a shippable state."
            )
            set_workflow_status(
                self.run,
                status="failed",
                summary=summary,
                extra={"branch_name": self.branch_name, "cycles": self.pipeline_cfg.max_cycles},
            )
            append_workflow_event(
                self.run,
                stage="workflow",
                status="failed",
                message=summary,
                details={"branch": self.branch_name, "cycles": self.pipeline_cfg.max_cycles},
            )
            await self.channel.send(f"⚠️ {summary}")
            return PipelineExecutionResult(
                success=False,
                run=self.run,
                branch_name=self.branch_name,
                cycle=self.pipeline_cfg.max_cycles,
                duration=time.monotonic() - started,
                summary=summary,
            )
        except Exception as exc:
            cancelled = "cancelled by user" in str(exc).lower()
            summary = "Pipeline cancelled by user." if cancelled else f"Pipeline failed: {exc}"
            set_workflow_status(
                self.run,
                status="cancelled" if cancelled else "failed",
                summary=summary,
                extra={"branch_name": self.branch_name, "cycles": self.cycle},
            )
            append_workflow_event(
                self.run,
                stage="workflow",
                status="cancelled" if cancelled else "failed",
                message=summary,
                details={"branch": self.branch_name, "cycles": self.cycle},
            )
            await self.channel.send(f"{'🛑' if cancelled else '❌'} {summary}")
            return PipelineExecutionResult(
                success=False,
                run=self.run,
                branch_name=self.branch_name,
                cycle=self.cycle,
                duration=time.monotonic() - started,
                summary=summary,
            )

    async def _create_branch(self) -> str:
        branch_name = await self._next_branch_name()
        await self._run_shell_step(
            stage="branch",
            command=f"git checkout -b {branch_name}",
            artifact_name="branch-command.txt",
            fail_message="Failed to create feature branch.",
        )
        await self.channel.send(f"🌿 Created branch `{branch_name}`.")
        return branch_name

    async def _maybe_create_plan(self) -> str:
        if not _needs_plan(self.pipeline_cfg.plan_threshold, self.task):
            append_workflow_event(
                self.run,
                stage="planner",
                status="skipped",
                message="Plan step skipped by plan_threshold.",
                details={"plan_threshold": self.pipeline_cfg.plan_threshold},
            )
            return ""

        cli_key = self._resolve_cli("planner")
        project_context = load_project_context(self.project_path, self.config, self.project_name)
        prompt = "\n\n".join(
            [
                "Create a concise execution plan for this feature delivery workflow.",
                build_project_profile_summary(self.project_name, self.project_cfg),
                f"Task:\n{self.task}",
                "Output format:\n1. Scope\n2. Implementation steps\n3. Risks\n4. Validation plan",
                f"Project context:\n{project_context[:12000]}",
            ]
        )
        write_artifact(self.run, "planner-prompt.md", prompt)
        result = await self._run_cli_step(
            cli_key=cli_key,
            stage="planner",
            prompt=prompt,
            artifact_name="plan.md",
        )
        return result.transcript.strip()

    async def _run_coder(self) -> None:
        cli_key = self._resolve_cli("coder")
        project_context = load_project_context(self.project_path, self.config, self.project_name)

        task_parts = []
        if self._plan_text:
            task_parts.append("Plan to follow:\n" + self._plan_text)
        if self._feedback:
            task_parts.append("Address this feedback before stopping:\n" + self._feedback)
        task_parts.append("Implement this feature in the repository:\n" + self.task)
        task_parts.append(
            "Stop condition:\n"
            "- finish the code change\n"
            "- keep existing behavior unless the task says otherwise\n"
            "- update validation only if the change requires it\n"
            "- stop after the implementation is complete"
        )
        task_text = "\n\n".join(task_parts)
        if cli_key == "codex":
            compact_parts = [
                f"Project: {self.project_name}.",
                f"Run directory: {self.run.run_dir}.",
                task_text.replace("\n", " "),
            ]
            if project_context:
                compact_parts.append(
                    "Project context summary: "
                    + _one_line(project_context[:2000])
                )
            prompt = " ".join(part.strip() for part in compact_parts if part.strip())
        else:
            prompt = build_cli_task_prompt(
                task=task_text,
                project_name=self.project_name,
                project_cfg=self.project_cfg,
                project_context=project_context,
                files=[],
                run=self.run,
            )
        write_artifact(self.run, f"cycle-{self.cycle}-coder-prompt.md", prompt)
        await self._run_cli_step(
            cli_key=cli_key,
            stage="coder",
            prompt=prompt,
            artifact_name=f"cycle-{self.cycle}-coder-output.md",
        )

    async def _run_lint(self) -> bool:
        command = self.pipeline_cfg.lint_command.strip()
        if not command:
            append_workflow_event(
                self.run,
                stage="lint",
                status="skipped",
                message="Lint step skipped because no lint command is configured.",
            )
            return True

        result = await self._run_shell_step(
            stage="lint",
            command=command,
            artifact_name=f"cycle-{self.cycle}-lint.txt",
            allow_failure=True,
            fail_message="Lint command failed.",
        )
        if result.returncode == 0:
            return True

        self._feedback = await self._interpret_failure(
            stage="lint",
            command=command,
            output=result.output,
            artifact_name=f"cycle-{self.cycle}-lint-analysis.md",
        )
        return False

    async def _commit(self) -> None:
        await self._run_shell_step(
            stage="commit",
            command="git add -A",
            artifact_name=f"cycle-{self.cycle}-git-add.txt",
            fail_message="Failed to stage changes.",
        )
        await self._run_shell_step(
            stage="commit",
            command="git reset -- .devbot/runs",
            artifact_name=f"cycle-{self.cycle}-git-reset-devbot.txt",
            allow_failure=True,
            fail_message="",
        )
        commit_message = _clip_commit_message(self.task, self.cycle) + "\n"
        message_path = write_artifact(
            self.run,
            f"cycle-{self.cycle}-commit-message.txt",
            commit_message,
        )
        message_rel = Path(message_path).relative_to(Path(self.project_path)).as_posix()
        await self._run_shell_step(
            stage="commit",
            command=f"git commit -F {message_rel} --allow-empty",
            artifact_name=f"cycle-{self.cycle}-git-commit.txt",
            fail_message="Failed to create commit.",
        )

    async def _run_review(self) -> bool:
        diff_output = await self._collect_diff()
        write_artifact(self.run, f"cycle-{self.cycle}-diff.md", diff_output)

        reviewers = list(self.pipeline_cfg.reviewers)
        if not reviewers:
            reviewers = [self._resolve_cli("reviewer")]

        self._review_reports = []
        for index, reviewer_cli in enumerate(reviewers, start=1):
            prompt = "\n\n".join(
                [
                    "Review the changes below. Be strict about correctness, regressions, and missing validation.",
                    "You MUST end the response with exactly one final line:",
                    "VERDICT: APPROVED",
                    "or",
                    "VERDICT: CHANGES_REQUESTED",
                    f"Task:\n{self.task}",
                    f"Diff against {self.pipeline_cfg.base_branch}:\n```diff\n{diff_output[:18000]}\n```",
                ]
            )
            write_artifact(self.run, f"cycle-{self.cycle}-reviewer-{index}-prompt.md", prompt)
            result = await self._run_cli_step(
                cli_key=reviewer_cli,
                stage="review",
                prompt=prompt,
                artifact_name=f"cycle-{self.cycle}-reviewer-{index}.md",
            )
            report = result.transcript.strip()
            self._review_reports.append(report)
            verdict = _parse_review_verdict(report)
            append_workflow_event(
                self.run,
                stage="review",
                status="completed" if verdict == "APPROVED" else "failed",
                message=f"Reviewer {reviewer_cli} returned {verdict}.",
                details={"cli": reviewer_cli, "cycle": self.cycle},
            )
            await self.channel.send(f"🔍 Reviewer `{reviewer_cli}` verdict: `{verdict}`.")
            if verdict != "APPROVED":
                self._feedback = report
                return False

        self._feedback = ""
        return True

    async def _run_tests(self) -> bool:
        command = self.pipeline_cfg.test_command.strip()
        if not command:
            append_workflow_event(
                self.run,
                stage="qa",
                status="skipped",
                message="QA test step skipped because no test command is configured.",
            )
            self._qa_reports = []
            return True

        result = await self._run_shell_step(
            stage="qa",
            command=command,
            artifact_name=f"cycle-{self.cycle}-qa.txt",
            allow_failure=True,
            fail_message="Test command failed.",
        )
        if result.returncode == 0:
            self._qa_reports = []
            return True

        qa_feedback = await self._interpret_failure(
            stage="qa",
            command=command,
            output=result.output,
            artifact_name=f"cycle-{self.cycle}-qa-analysis.md",
        )
        self._feedback = qa_feedback
        self._qa_reports = [qa_feedback]
        return False

    async def _release(self) -> tuple[str, str]:
        lines = [
            f"Task: {self.task}",
            f"Branch: {self.branch_name}",
            f"Cycles: {self.cycle}",
        ]
        if self._review_reports:
            lines.append("Review: APPROVED")
        if self.pipeline_cfg.test_command:
            lines.append(f"QA command: {self.pipeline_cfg.test_command}")
        summary = "\n".join(lines) + "\n"
        write_artifact(self.run, "release-summary.md", summary)
        append_workflow_event(
            self.run,
            stage="release",
            status="started",
            message="Release step started.",
            details={"branch": self.branch_name},
        )

        push_status = await self._push_branch()
        pr_status = await self._maybe_create_pr()
        append_workflow_event(
            self.run,
            stage="release",
            status="completed",
            message="Release step finished.",
            details={"push_status": push_status, "pr_status": pr_status},
        )
        return push_status, pr_status

    async def _push_branch(self) -> str:
        remote = self.pipeline_cfg.push_remote.strip() or "origin"
        remote_check = await self._run_shell_step(
            stage="push",
            command=f"git remote get-url {remote}",
            artifact_name="push-remote.txt",
            allow_failure=True,
            fail_message=f"Remote `{remote}` is not configured.",
        )
        if remote_check.returncode != 0:
            message = f"Skipped push because remote `{remote}` is not configured."
            append_workflow_event(
                self.run,
                stage="push",
                status="skipped",
                message=message,
                details={"remote": remote},
            )
            await self.channel.send(f"⚠️ {message}")
            return message

        push_result = await self._run_shell_step(
            stage="push",
            command=f"git push -u {remote} {self.branch_name}",
            artifact_name="push.txt",
            allow_failure=True,
            fail_message=f"Failed to push branch `{self.branch_name}`.",
        )
        if push_result.returncode != 0:
            raise RuntimeError(f"git push failed for `{self.branch_name}`.")

        message = f"Pushed `{self.branch_name}` to `{remote}`."
        await self.channel.send(f"📤 {message}")
        return message

    async def _maybe_create_pr(self) -> str:
        if not self.pipeline_cfg.auto_pr:
            message = "PR creation skipped because auto_pr is disabled."
            append_workflow_event(self.run, stage="pr", status="skipped", message=message)
            return message

        if self.pipeline_cfg.pr_tool != "gh":
            message = f"PR creation skipped because pr_tool `{self.pipeline_cfg.pr_tool}` is unsupported."
            append_workflow_event(self.run, stage="pr", status="skipped", message=message)
            return message

        if shutil.which("gh") is None:
            message = "PR creation skipped because `gh` is not on PATH."
            append_workflow_event(self.run, stage="pr", status="skipped", message=message)
            await self.channel.send(f"⚠️ {message}")
            return message

        auth = await self._run_shell_step(
            stage="pr",
            command="gh auth status",
            artifact_name="gh-auth.txt",
            allow_failure=True,
            fail_message="GitHub CLI auth check failed.",
        )
        if auth.returncode != 0:
            message = "PR creation skipped because `gh` is not authenticated."
            append_workflow_event(self.run, stage="pr", status="skipped", message=message)
            await self.channel.send(f"⚠️ {message}")
            return message

        title = _pr_title(self.task)
        body = _pr_body(self.task, self.branch_name, self.cycle, self.pipeline_cfg.base_branch)
        body_path = write_artifact(self.run, "pr-body.md", body)
        body_rel = Path(body_path).relative_to(Path(self.project_path)).as_posix()
        write_artifact(self.run, "pr-title.txt", title + "\n")
        pr_result = await self._run_shell_step(
            stage="pr",
            command=(
                f'gh pr create --title "{title}" --body-file {body_rel} '
                f"--base {self.pipeline_cfg.base_branch} --head {self.branch_name}"
            ),
            artifact_name="pr-create.txt",
            allow_failure=True,
            fail_message="GitHub CLI PR creation failed.",
        )
        if pr_result.returncode != 0:
            message = "PR creation failed even though `gh` is installed and authenticated."
            append_workflow_event(self.run, stage="pr", status="failed", message=message)
            raise RuntimeError(message)

        message = f"PR created for `{self.branch_name}`."
        await self.channel.send(f"📬 {message}")
        return message

    async def _collect_diff(self) -> str:
        command = f"git diff {self.pipeline_cfg.base_branch}...HEAD"
        result = await self._run_shell_step(
            stage="review",
            command=command,
            artifact_name=f"cycle-{self.cycle}-diff-command.txt",
            allow_failure=True,
            fail_message="Failed to collect diff against base branch.",
        )
        if result.returncode == 0 and result.output.strip():
            return result.output

        fallback = await self._run_shell_step(
            stage="review",
            command="git show --stat --patch --format=medium HEAD",
            artifact_name=f"cycle-{self.cycle}-diff-fallback.txt",
            allow_failure=True,
            fail_message="Failed to collect fallback diff.",
        )
        return fallback.output or "(no diff output)"

    async def _interpret_failure(
        self,
        *,
        stage: str,
        command: str,
        output: str,
        artifact_name: str,
    ) -> str:
        tester_cli = self._resolve_cli("qa")
        prompt = "\n\n".join(
            [
                f"Analyze this {stage} failure and give precise next steps for the coder.",
                f"Original task:\n{self.task}",
                f"Command:\n{command}",
                f"Output:\n```\n{output[:12000]}\n```",
                "Respond with:\n1. Root cause\n2. Required fixes\n3. Validation to rerun",
            ]
        )
        write_artifact(self.run, artifact_name.replace(".md", "-prompt.md"), prompt)
        result = await self._run_cli_step(
            cli_key=tester_cli,
            stage=stage,
            prompt=prompt,
            artifact_name=artifact_name,
        )
        return result.transcript.strip() or _trim_output(output)

    async def _run_cli_step(
        self,
        *,
        cli_key: str,
        stage: str,
        prompt: str,
        artifact_name: str,
    ) -> "TaskResult":
        self._ensure_not_cancelled()
        self._ensure_cli_available(cli_key)
        adapter = build_adapter(cli_key, self.config)
        append_workflow_event(
            self.run,
            stage=stage,
            status="started",
            message=f"Running `{cli_key}`.",
            details={"cli": cli_key, "cycle": self.cycle},
        )
        result = await self.task_manager.execute(
            adapter=adapter,
            task=prompt,
            project_path=self.project_path,
            project_name=self.project_name,
            channel=self.channel,
            workflow=self.run.workflow,
            run_id=self.run.run_id,
            log_path=str(self.run.run_dir / "timeline.md"),
        )
        write_artifact(self.run, artifact_name, result.transcript or "(no output)")
        append_workflow_event(
            self.run,
            stage=stage,
            status="completed" if result.returncode == 0 else "failed",
            message=f"`{cli_key}` finished with exit code {result.returncode}.",
            details={"cli": cli_key, "cycle": self.cycle, "returncode": result.returncode},
        )
        if result.returncode != 0:
            raise RuntimeError(f"{stage} step failed via `{cli_key}`.")
        return result

    async def _run_shell_step(
        self,
        *,
        stage: str,
        command: str,
        artifact_name: str,
        allow_failure: bool = False,
        fail_message: str = "",
    ):
        self._ensure_not_cancelled()
        append_workflow_event(
            self.run,
            stage=stage,
            status="started",
            message=f"Running shell command `{command}`.",
            details={"cycle": self.cycle},
        )
        result = await run_shell(
            command=command,
            shell="auto",
            working_dir=self.project_path,
            timeout=self.config.shell.timeout,
            platform_info=self.platform_info,
        )
        artifact_text = f"$ {command}\n\n{result.output or '(no output)'}\n"
        write_artifact(self.run, artifact_name, artifact_text)
        append_workflow_event(
            self.run,
            stage=stage,
            status="completed" if result.returncode == 0 else "failed",
            message=f"Shell command finished with exit code {result.returncode}.",
            details={"cycle": self.cycle, "returncode": result.returncode},
        )
        if result.returncode != 0 and not allow_failure:
            raise RuntimeError(fail_message or f"Shell step `{stage}` failed.")
        return result

    async def _next_branch_name(self) -> str:
        base = _slugify_branch(self.task)
        candidate = f"feature/{base}"
        counter = 2
        while True:
            check = await self._run_shell_step(
                stage="branch",
                command=f"git rev-parse --verify {candidate}",
                artifact_name=f"branch-check-{counter}.txt",
                allow_failure=True,
                fail_message="",
            )
            if check.returncode != 0:
                return candidate
            candidate = f"feature/{base}-{counter}"
            counter += 1

    def _resolve_cli(self, role_name: str) -> str:
        if role_name == "coder" and self.pipeline_cfg.coder:
            return self.pipeline_cfg.coder
        if role_name == "qa" and self.pipeline_cfg.tester:
            return self.pipeline_cfg.tester
        if role_name == "reviewer" and self.pipeline_cfg.reviewers:
            return self.pipeline_cfg.reviewers[0]
        return select_cli_for_role(role_name, self.config, project_name=self.project_name)

    def _ensure_cli_available(self, cli_key: str) -> None:
        info = self.task_manager.current_cli_info(cli_key)
        if info is not None and info.project != self.project_name:
            raise RuntimeError(f"CLI `{cli_key}` is already busy on `{info.project}`.")
        cli_cfg = getattr(self.config.cli, cli_key, None)
        if cli_cfg is None or not cli_cfg.enabled:
            raise RuntimeError(f"CLI `{cli_key}` is unavailable for pipeline execution.")
        adapter = build_adapter(cli_key, self.config)
        if not adapter.is_available():
            raise RuntimeError(f"`{cli_cfg.command}` is not on PATH.")

    def _ensure_not_cancelled(self) -> None:
        if self.cancel_requested and self.cancel_requested():
            raise RuntimeError("Pipeline cancelled by user.")

    def _ensure_local_git_exclude(self) -> None:
        git_dir = Path(self.project_path) / ".git"
        exclude_path = git_dir / "info" / "exclude"
        if not exclude_path.exists():
            return
        line = ".devbot/runs/"
        existing = exclude_path.read_text(encoding="utf-8")
        if line in existing:
            return
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        exclude_path.write_text(existing + prefix + line + "\n", encoding="utf-8")


def _resolve_pipeline_config(
    config: "Config",
    project_name: str,
    project_cfg: "ProjectConfig",
) -> "PipelineConfig":
    merged = project_cfg.pipeline
    coder = merged.coder or project_cfg.role_preferences.get("coder") or select_cli_for_role(
        "coder",
        config,
        project_name=project_name,
    )
    reviewers = list(merged.reviewers)
    if not reviewers:
        reviewers = [project_cfg.role_preferences.get("reviewer") or select_cli_for_role("reviewer", config, project_name=project_name)]
    tester = (
        merged.tester
        or project_cfg.role_preferences.get("qa")
        or project_cfg.role_preferences.get("tester")
        or select_cli_for_role(
        "qa",
        config,
        project_name=project_name,
        )
    )
    return type(merged)(
        coder=coder,
        reviewers=reviewers,
        tester=tester,
        test_command=merged.test_command or project_cfg.commands.test,
        lint_command=merged.lint_command or " && ".join(project_cfg.commands.smoke).strip(),
        max_cycles=merged.max_cycles,
        auto_pr=merged.auto_pr,
        pr_tool=merged.pr_tool,
        base_branch=merged.base_branch,
        plan_threshold=merged.plan_threshold,
        push_remote=merged.push_remote,
    )


def _pipeline_metadata(cfg: "PipelineConfig") -> dict[str, object]:
    return {
        "coder": cfg.coder,
        "reviewers": list(cfg.reviewers),
        "tester": cfg.tester,
        "test_command": cfg.test_command,
        "lint_command": cfg.lint_command,
        "max_cycles": cfg.max_cycles,
        "auto_pr": cfg.auto_pr,
        "pr_tool": cfg.pr_tool,
        "base_branch": cfg.base_branch,
        "plan_threshold": cfg.plan_threshold,
        "push_remote": cfg.push_remote,
    }


def _needs_plan(threshold: str, task: str) -> bool:
    wanted = (threshold or "complex").strip().lower()
    if wanted == "always":
        return True
    if wanted == "never":
        return False
    task_lower = task.lower()
    complexity_signals = ("refactor", "migration", "workflow", "pipeline", "across", "multiple", "end to end")
    return len(task) > 90 or any(signal in task_lower for signal in complexity_signals)


def _parse_review_verdict(output: str) -> str:
    for line in reversed(output.splitlines()):
        candidate = line.strip().upper()
        if candidate.startswith("VERDICT:"):
            if "APPROVED" in candidate:
                return "APPROVED"
            if "CHANGES_REQUESTED" in candidate:
                return "CHANGES_REQUESTED"
    return "CHANGES_REQUESTED"


def _slugify_branch(task: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", task.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug[:48] or f"task-{int(time.time())}").strip("-")


def _clip_commit_message(task: str, cycle: int) -> str:
    clean = re.sub(r"\s+", " ", task).strip().replace('"', "'")
    return f"devbot: cycle {cycle} - {clean[:54]}".strip()


def _pr_title(task: str) -> str:
    text = re.sub(r"\s+", " ", task).strip().replace('"', "'")
    return text[:72] or "DevBot pipeline update"


def _pr_body(task: str, branch_name: str, cycle: int, base_branch: str) -> str:
    return "\n".join(
        [
            "## Summary",
            task,
            "",
            "## Workflow",
            f"- Branch: `{branch_name}`",
            f"- Base: `{base_branch}`",
            f"- Cycles: `{cycle}`",
        ]
    )


def _trim_output(output: str, limit: int = 1200) -> str:
    if len(output) <= limit:
        return output
    return output[: limit - 3] + "..."


def _one_line(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
