"""Focused auto-restart test.

Run with:
  conda run -n devbot python test_auto_restart.py
"""

from __future__ import annotations

import asyncio
import platform
import shutil
from pathlib import Path

from devbot.bot.client import DevBotClient
from devbot.config.settings import (
    CLIConfig,
    CLIToolConfig,
    Config,
    ContextConfig,
    DiscordConfig,
    LLMConfig,
    LLMProviderConfig,
    ProjectConfig,
    ProjectCommandsConfig,
    ReporterConfig,
    ShellConfig,
    TodoConfig,
)
from devbot.executor.auto_restart import capture_project_snapshot


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


def _restart_command() -> tuple[str, str]:
    if platform.system() == "Windows":
        return "echo restarted> restart-marker.txt", "cmd"
    return "printf restarted > restart-marker.txt", "bash"


def build_config(root: Path, auto_restart: bool = True) -> Config:
    project_path = root / "alpha"
    project_path.mkdir(parents=True, exist_ok=True)
    (project_path / "app.py").write_text("print('alpha')\n", encoding="utf-8")
    (project_path / "README.md").write_text("# Alpha\n", encoding="utf-8")
    restart_command, restart_shell = _restart_command()

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
        shell=ShellConfig(default="auto", timeout=30, wsl_distro=None),
        todo=TodoConfig(file=root / "todos.md", done_file=root / "done.md"),
        context=ContextConfig(),
        reporter=ReporterConfig(),
        projects={
            "alpha": ProjectConfig(
                path=project_path,
                auto_restart=auto_restart,
                commands=ProjectCommandsConfig(
                    restart=restart_command,
                    restart_shell=restart_shell,
                ),
            )
        },
        services={},
        team_roles={},
        workflows={},
    )


async def main() -> None:
    auto_root = Path(".tmp-auto-restart")
    manual_root = Path(".tmp-project-restart")
    shutil.rmtree(auto_root, ignore_errors=True)
    shutil.rmtree(manual_root, ignore_errors=True)
    auto_root.mkdir(parents=True, exist_ok=True)
    manual_root.mkdir(parents=True, exist_ok=True)

    auto_client = None
    manual_client = None
    try:
        config = build_config(auto_root, auto_restart=True)
        channel = FakeChannel()
        project_path = config.projects["alpha"].path

        auto_client = DevBotClient(config)

        snapshot = capture_project_snapshot(str(project_path))
        (project_path / "app.py").write_text("print('changed')\n", encoding="utf-8")
        result = await auto_client._maybe_auto_restart_project(
            project_name="alpha",
            project_path=str(project_path),
            snapshot=snapshot,
            channel=channel,
        )
        assert result.attempted
        assert result.restarted
        assert (project_path / "restart-marker.txt").exists()

        (project_path / "restart-marker.txt").unlink()
        snapshot = capture_project_snapshot(str(project_path))
        (project_path / "README.md").write_text("# Alpha updated\n", encoding="utf-8")
        result = await auto_client._maybe_auto_restart_project(
            project_name="alpha",
            project_path=str(project_path),
            snapshot=snapshot,
            channel=channel,
        )
        assert not result.attempted
        assert not (project_path / "restart-marker.txt").exists()
        assert any("Auto-restarted `alpha`" in message for message in channel.messages), channel.messages

        manual_config = build_config(manual_root, auto_restart=False)
        manual_project_path = manual_config.projects["alpha"].path
        manual_client = DevBotClient(manual_config)
        success, reply = await manual_client._restart_project_now("alpha", str(manual_project_path))
        assert success, reply
        assert "Restarted `alpha`" in reply
        assert (manual_project_path / "restart-marker.txt").exists()
        print("Auto restart test passed.")
    finally:
        if auto_client is not None:
            await auto_client.close()
        if manual_client is not None:
            await manual_client.close()
        shutil.rmtree(auto_root, ignore_errors=True)
        shutil.rmtree(manual_root, ignore_errors=True)


asyncio.run(main())
