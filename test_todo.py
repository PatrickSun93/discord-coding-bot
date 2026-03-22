"""Focused todo queue test.

Run with:
  conda run -n devbot python test_todo.py
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from devbot.config.settings import (
    CLIConfig,
    CLIToolConfig,
    Config,
    ContextConfig,
    DiscordConfig,
    LLMConfig,
    LLMProviderConfig,
    ProjectConfig,
    ReporterConfig,
    ShellConfig,
    TodoConfig,
)
from devbot.executor.manager import TaskManager
from devbot.todo import (
    TodoExecutor,
    TodoItem,
    TodoRunResult,
    add_todo_item,
    parse_todo_file,
    prepare_todo_item,
)


class FakeChannel:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send(self, content=None, embed=None):
        if content is not None:
            self.messages.append(str(content))
        elif embed is not None:
            self.messages.append(f"<embed:{embed.title}>")
        else:
            self.messages.append("<empty>")
        return self

    async def edit(self, content=None, embed=None):
        if content is not None:
            self.messages.append(str(content))
        elif embed is not None:
            self.messages.append(f"<embed:{embed.title}>")
        return self


def _tool(command: str, roles: list[str]) -> CLIToolConfig:
    return CLIToolConfig(
        command=command,
        base_args=[],
        autonomy_args=[],
        extra_args=[],
        timeout=30,
        enabled=True,
        roles=roles,
    )


def build_config(root: Path) -> Config:
    todo_dir = root / ".devbot-home"
    projects = {
        "alpha": ProjectConfig(path=root / "alpha"),
        "beta": ProjectConfig(path=root / "beta", role_preferences={"coder": "codex"}),
    }

    for project in projects.values():
        project.path.mkdir(parents=True, exist_ok=True)
        (project.path / "README.md").write_text("# Test project\n", encoding="utf-8")

    return Config(
        discord=DiscordConfig(token="x", owner_id=1, channel_id=None),
        llm=LLMConfig(
            primary=LLMProviderConfig(provider="minimax", base_url="", model="", api_key=""),
            fallback=LLMProviderConfig(provider="ollama", base_url="", model="", api_key="ollama"),
        ),
        cli=CLIConfig(
            claude_code=_tool("cmd", ["coder"]),
            codex=_tool("cmd", ["coder"]),
            gemini_cli=_tool("cmd", ["reviewer", "tester"]),
            qwen_cli=_tool("cmd", ["reviewer"]),
        ),
        shell=ShellConfig(),
        todo=TodoConfig(
            file=todo_dir / "todos.md",
            done_file=todo_dir / "done.md",
            auto_start=False,
            busy_cli_timeout=30,
        ),
        context=ContextConfig(),
        reporter=ReporterConfig(),
        projects=projects,
        services={},
        team_roles={},
        workflows={},
    )


async def main() -> None:
    root = Path(".tmp-todo")
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)

    try:
        config = build_config(root)
        task_manager = TaskManager(config)
        executor = TodoExecutor(config, task_manager)
        channel = FakeChannel()

        add_todo_item(
            config.todo.file,
            TodoItem(item_id="1", priority=1, cli="claude", project="alpha", task="Fix alpha bug"),
        )
        add_todo_item(
            config.todo.file,
            TodoItem(item_id="2", priority=1, cli="codex", project="beta", task="Refactor beta service"),
        )
        add_todo_item(
            config.todo.file,
            TodoItem(item_id="3", priority=2, cli="pipeline", project="beta", task="Ship beta change"),
        )

        items = parse_todo_file(config.todo.file)
        assert len(items) == 3, items

        pipeline_item, issue = prepare_todo_item(items[-1], config)
        assert issue is None
        assert pipeline_item is not None
        assert pipeline_item.mode == "pipeline"
        assert pipeline_item.cli_key == "codex"

        active_cli: set[str] = set()
        max_active = 0

        async def fake_runner(item, _channel):
            nonlocal max_active
            active_cli.add(item.cli_key)
            max_active = max(max_active, len(active_cli))
            await asyncio.sleep(0.05)
            active_cli.remove(item.cli_key)
            return TodoRunResult(
                item=item,
                status="success",
                duration=0.05,
                summary=f"finished {item.item.task}",
                returncode=0,
            )

        started, reply = await executor.start(channel, fake_runner)
        assert started, reply
        assert "Starting todo queue" in reply

        await executor.wait_closed()

        remaining = parse_todo_file(config.todo.file)
        assert not remaining, remaining
        assert config.todo.done_file.exists()
        done_text = config.todo.done_file.read_text(encoding="utf-8")
        assert "Fix alpha bug" in done_text
        assert "Ship beta change" in done_text
        assert max_active >= 2, max_active
        assert any("Priority 1" in message for message in channel.messages), channel.messages
        assert any("Todo queue complete" in message for message in channel.messages), channel.messages
        print("Todo queue test passed.")
    finally:
        shutil.rmtree(root, ignore_errors=True)


asyncio.run(main())
