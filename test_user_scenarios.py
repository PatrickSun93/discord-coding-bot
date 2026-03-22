"""Scenario-driven tests for queue, restart, and slash-command behavior.

Run with:
  conda run -n devbot python -m unittest -v test_user_scenarios.py
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from devbot.bot.client import DevBotClient
from devbot.config.settings import ServiceConfig
from devbot.executor.auto_restart import capture_project_snapshot
from devbot.executor.manager import TaskInfo, TaskManager
from devbot.todo import TodoExecutor, TodoItem, TodoRunResult, add_todo_item, parse_todo_file
from test_support import (
    FakeChannel,
    FakeInteraction,
    build_config,
    restart_success_command,
)


def _project_restart_command(bot: DevBotClient):
    project_group = next(command for command in bot.tree.get_commands() if command.name == "project")
    return next(command for command in project_group.commands if command.name == "restart")


class TodoScenarioTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.config = build_config(self.root)
        self.task_manager = TaskManager(self.config)
        self.executor = TodoExecutor(self.config, self.task_manager)
        self.channel = FakeChannel()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_parallelizes_distinct_clis_on_distinct_projects(self) -> None:
        add_todo_item(
            self.config.todo.file,
            TodoItem(item_id="1", priority=1, cli="claude", project="alpha", task="Fix alpha"),
        )
        add_todo_item(
            self.config.todo.file,
            TodoItem(item_id="2", priority=1, cli="codex", project="beta", task="Fix beta"),
        )
        add_todo_item(
            self.config.todo.file,
            TodoItem(item_id="3", priority=1, cli="gemini", project="gamma", task="Review gamma"),
        )

        active_clis: set[str] = set()
        active_projects: set[str] = set()
        max_active = 0

        async def fake_runner(item, _channel):
            nonlocal max_active
            self.assertNotIn(item.cli_key, active_clis)
            self.assertNotIn(item.project_name, active_projects)
            active_clis.add(item.cli_key)
            active_projects.add(item.project_name)
            max_active = max(max_active, len(active_clis))
            await asyncio.sleep(0.05)
            active_clis.remove(item.cli_key)
            active_projects.remove(item.project_name)
            return TodoRunResult(
                item=item,
                status="success",
                duration=0.05,
                summary=f"finished {item.item.task}",
                returncode=0,
            )

        started, reply = await self.executor.start(self.channel, fake_runner)
        self.assertTrue(started, reply)
        await self.executor.wait_closed()

        self.assertEqual(max_active, 3)
        self.assertEqual(parse_todo_file(self.config.todo.file), [])
        self.assertTrue(self.config.todo.done_file.exists())
        self.assertIn("Todo queue complete. 3/3 succeeded, 0 failed, 0 cancelled.", self.channel.messages[-1])

    async def test_serializes_same_cli_across_projects(self) -> None:
        add_todo_item(
            self.config.todo.file,
            TodoItem(item_id="1", priority=1, cli="claude", project="alpha", task="Alpha one"),
        )
        add_todo_item(
            self.config.todo.file,
            TodoItem(item_id="2", priority=1, cli="claude", project="beta", task="Beta one"),
        )

        active_claude = 0
        max_claude = 0

        async def fake_runner(item, _channel):
            nonlocal active_claude, max_claude
            if item.cli_key == "claude_code":
                active_claude += 1
                max_claude = max(max_claude, active_claude)
            await asyncio.sleep(0.03)
            if item.cli_key == "claude_code":
                active_claude -= 1
            return TodoRunResult(item=item, status="success", duration=0.03, returncode=0)

        started, reply = await self.executor.start(self.channel, fake_runner)
        self.assertTrue(started, reply)
        await self.executor.wait_closed()

        self.assertEqual(max_claude, 1)

    async def test_validation_failure_blocks_queue_start(self) -> None:
        bad_config = build_config(
            self.root / "bad-config",
            cli_commands={"claude_code": "definitely-not-a-real-command"},
        )
        executor = TodoExecutor(bad_config, TaskManager(bad_config))
        add_todo_item(
            bad_config.todo.file,
            TodoItem(item_id="1", priority=1, cli="claude", project="alpha", task="Broken CLI"),
        )

        started, reply = await executor.start(self.channel, lambda *_args: None)
        self.assertFalse(started)
        self.assertIn("Todo validation failed", reply)
        self.assertIn("not on PATH", reply)

    async def test_runner_exception_becomes_failed_result(self) -> None:
        add_todo_item(
            self.config.todo.file,
            TodoItem(item_id="1", priority=1, cli="claude", project="alpha", task="Crash task"),
        )

        async def exploding_runner(_item, _channel):
            raise RuntimeError("boom")

        started, reply = await self.executor.start(self.channel, exploding_runner)
        self.assertTrue(started, reply)
        await self.executor.wait_closed()

        remaining = parse_todo_file(self.config.todo.file)
        self.assertEqual(remaining, [])
        done_text = self.config.todo.done_file.read_text(encoding="utf-8")
        self.assertIn("Crash task", done_text)
        self.assertIn("Failed", done_text)
        self.assertIn("boom", done_text)
        self.assertTrue(any("❌ Failed" in message for message in self.channel.messages))
        self.assertTrue(any("1 failed" in message for message in self.channel.messages))

    async def test_cancel_stops_new_dispatch_after_request(self) -> None:
        add_todo_item(
            self.config.todo.file,
            TodoItem(item_id="1", priority=1, cli="claude", project="alpha", task="Alpha active"),
        )
        add_todo_item(
            self.config.todo.file,
            TodoItem(item_id="2", priority=1, cli="codex", project="alpha", task="Alpha blocked"),
        )
        add_todo_item(
            self.config.todo.file,
            TodoItem(item_id="3", priority=1, cli="gemini", project="beta", task="Beta active"),
        )

        active_started = asyncio.Event()
        release_alpha = asyncio.Event()
        release_beta = asyncio.Event()
        codex_started = asyncio.Event()
        running: set[str] = set()

        async def fake_runner(item, _channel):
            running.add(item.item.task)
            if {"Alpha active", "Beta active"}.issubset(running):
                active_started.set()

            if item.item.task == "Alpha active":
                await release_alpha.wait()
            elif item.item.task == "Beta active":
                await release_beta.wait()
            else:
                codex_started.set()

            running.discard(item.item.task)
            return TodoRunResult(item=item, status="success", duration=0.01, returncode=0)

        started, reply = await self.executor.start(self.channel, fake_runner)
        self.assertTrue(started, reply)
        await asyncio.wait_for(active_started.wait(), timeout=2)

        cancelled = await self.executor.cancel()
        self.assertTrue(cancelled)

        release_alpha.set()
        await asyncio.sleep(0.2)
        self.assertFalse(codex_started.is_set())

        release_beta.set()
        await self.executor.wait_closed()

        remaining = parse_todo_file(self.config.todo.file)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0].task, "Alpha blocked")
        self.assertTrue(any("Todo queue stopped" in message for message in self.channel.messages))


class RestartScenarioTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.clients: list[DevBotClient] = []

    async def asyncTearDown(self) -> None:
        for client in self.clients:
            await client.close()
        self.temp_dir.cleanup()

    def build_client(self, config) -> DevBotClient:
        client = DevBotClient(config)
        self.clients.append(client)
        return client

    async def test_auto_restart_runs_for_code_change_only(self) -> None:
        restart_command, restart_shell = restart_success_command()
        config = build_config(
            self.root / "auto",
            project_specs={
                "alpha": {
                    "auto_restart": True,
                    "restart": restart_command,
                    "restart_shell": restart_shell,
                }
            },
        )
        client = self.build_client(config)
        channel = FakeChannel()
        project_path = config.projects["alpha"].path

        snapshot = capture_project_snapshot(str(project_path))
        (project_path / "app.py").write_text("print('changed')\n", encoding="utf-8")
        result = await client._maybe_auto_restart_project(
            project_name="alpha",
            project_path=str(project_path),
            snapshot=snapshot,
            channel=channel,
        )
        self.assertTrue(result.restarted)
        self.assertTrue((project_path / "restart-marker.txt").exists())

        (project_path / "restart-marker.txt").unlink()
        snapshot = capture_project_snapshot(str(project_path))
        (project_path / "README.md").write_text("# Docs only\n", encoding="utf-8")
        result = await client._maybe_auto_restart_project(
            project_name="alpha",
            project_path=str(project_path),
            snapshot=snapshot,
            channel=channel,
        )
        self.assertFalse(result.attempted)
        self.assertFalse((project_path / "restart-marker.txt").exists())

    async def test_manual_restart_works_when_auto_restart_is_disabled(self) -> None:
        restart_command, restart_shell = restart_success_command()
        config = build_config(
            self.root / "manual",
            project_specs={
                "alpha": {
                    "auto_restart": False,
                    "restart": restart_command,
                    "restart_shell": restart_shell,
                }
            },
        )
        client = self.build_client(config)

        success, reply = await client._restart_project_now("alpha", str(config.projects["alpha"].path))
        self.assertTrue(success, reply)
        self.assertIn("Restarted `alpha`", reply)
        self.assertTrue((config.projects["alpha"].path / "restart-marker.txt").exists())
        runs = list((config.projects["alpha"].path / ".devbot" / "runs" / "restart").glob("*"))
        self.assertEqual(len(runs), 1)
        self.assertTrue((runs[0] / "timeline.md").exists())
        self.assertTrue((runs[0] / "restart-output.txt").exists())
        self.assertIn("Logs:", reply)

    async def test_manual_restart_uses_service_fallback(self) -> None:
        restart_command, restart_shell = restart_success_command("service-restart.txt")
        config = build_config(
            self.root / "service",
            project_specs={
                "alpha": {
                    "auto_restart": False,
                    "restart_service": "api",
                }
            },
            service_specs={
                "api": ServiceConfig(shell=restart_shell, commands={"restart": restart_command}),
            },
        )
        client = self.build_client(config)

        success, reply = await client._restart_project_now("alpha", str(config.projects["alpha"].path))
        self.assertTrue(success, reply)
        self.assertIn("service `api`", reply)
        self.assertTrue((config.projects["alpha"].path / "service-restart.txt").exists())

    async def test_manual_restart_rejects_busy_and_blocklisted_projects(self) -> None:
        blocked_config = build_config(
            self.root / "blocked",
            project_specs={
                "alpha": {
                    "auto_restart": False,
                    "restart": "shutdown -h now",
                    "restart_shell": "bash",
                }
            },
        )
        blocked_client = self.build_client(blocked_config)
        success, reply = await blocked_client._restart_project_now(
            "alpha",
            str(blocked_config.projects["alpha"].path),
        )
        self.assertFalse(success)
        self.assertIn("blocked by the shell safety blocklist", reply)

        restart_command, restart_shell = restart_success_command()
        busy_config = build_config(
            self.root / "busy",
            project_specs={
                "alpha": {
                    "auto_restart": False,
                    "restart": restart_command,
                    "restart_shell": restart_shell,
                }
            },
        )
        busy_client = self.build_client(busy_config)
        busy_client.task_manager._tasks["alpha"] = TaskInfo(
            cli_name="claude_code",
            project="alpha",
            task="editing",
        )
        success, reply = await busy_client._restart_project_now(
            "alpha",
            str(busy_config.projects["alpha"].path),
        )
        self.assertFalse(success)
        self.assertIn("A task is already running", reply)

    async def test_auto_restart_reports_missing_config(self) -> None:
        config = build_config(
            self.root / "missing",
            project_specs={"alpha": {"auto_restart": True}},
        )
        client = self.build_client(config)
        channel = FakeChannel()
        project_path = config.projects["alpha"].path

        snapshot = capture_project_snapshot(str(project_path))
        (project_path / "app.py").write_text("print('changed again')\n", encoding="utf-8")
        result = await client._maybe_auto_restart_project(
            project_name="alpha",
            project_path=str(project_path),
            snapshot=snapshot,
            channel=channel,
        )

        self.assertTrue(result.failed)
        self.assertIn("no restart command is configured", result.message.lower())
        self.assertTrue(any("Auto-restart is enabled" in message for message in channel.messages))


class ProjectRestartCommandScenarioTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.config = build_config(self.root)
        self.client = DevBotClient(self.config)

    async def asyncTearDown(self) -> None:
        await self.client.close()
        self.temp_dir.cleanup()

    async def test_slash_restart_calls_shared_helper(self) -> None:
        command = _project_restart_command(self.client)
        interaction = FakeInteraction(user_id=self.config.discord.owner_id)
        self.client._restart_project_now = AsyncMock(return_value=(True, "ok"))

        await command.callback(interaction, name="alpha")

        self.client._restart_project_now.assert_awaited_once_with(
            "alpha",
            str(self.config.projects["alpha"].path),
        )
        self.assertEqual(interaction.response.messages, [("ok", False)])

    async def test_slash_restart_requires_owner(self) -> None:
        command = _project_restart_command(self.client)
        interaction = FakeInteraction(user_id=999)

        await command.callback(interaction, name="alpha")

        self.assertEqual(interaction.response.messages, [("⛔ Not authorized.", True)])

    async def test_slash_restart_rejects_unknown_or_path_input(self) -> None:
        command = _project_restart_command(self.client)
        owner_id = self.config.discord.owner_id

        interaction = FakeInteraction(user_id=owner_id)
        await command.callback(interaction, name="missing")
        self.assertTrue(interaction.response.messages)
        self.assertIn("Unknown project", interaction.response.messages[0][0])
        self.assertTrue(interaction.response.messages[0][1])

        absolute_path = self.root / "unregistered"
        absolute_path.mkdir(parents=True, exist_ok=True)
        interaction = FakeInteraction(user_id=owner_id)
        await command.callback(interaction, name=str(absolute_path))
        self.assertTrue(interaction.response.messages)
        self.assertIn("registered project name", interaction.response.messages[0][0])
        self.assertTrue(interaction.response.messages[0][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
