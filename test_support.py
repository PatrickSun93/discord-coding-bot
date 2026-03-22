"""Shared helpers for scenario-driven tests."""

from __future__ import annotations

import platform
from pathlib import Path

from devbot.config.settings import (
    CLIConfig,
    CLIToolConfig,
    Config,
    ContextConfig,
    DiscordConfig,
    LLMConfig,
    LLMProviderConfig,
    PipelineConfig,
    ProjectCommandsConfig,
    ProjectConfig,
    ReporterConfig,
    ServiceConfig,
    ShellConfig,
    TodoConfig,
)


def available_command() -> str:
    return "cmd" if platform.system() == "Windows" else "sh"


def restart_success_command(marker: str = "restart-marker.txt") -> tuple[str, str]:
    if platform.system() == "Windows":
        return f"echo restarted> {marker}", "cmd"
    return f"printf restarted > {marker}", "bash"


def restart_sleep_command(marker: str = "restart-marker.txt") -> tuple[str, str]:
    if platform.system() == "Windows":
        return f"ping -n 3 127.0.0.1 > nul && echo restarted> {marker}", "cmd"
    return f"sleep 2 && printf restarted > {marker}", "bash"


def build_config(
    root: Path,
    *,
    project_specs: dict[str, dict] | None = None,
    service_specs: dict[str, ServiceConfig] | None = None,
    cli_commands: dict[str, str] | None = None,
    disabled_clis: set[str] | None = None,
) -> Config:
    todo_home = root / ".devbot-home"
    command = available_command()
    cli_commands = cli_commands or {}
    disabled_clis = disabled_clis or set()
    project_specs = project_specs or {
        "alpha": {},
        "beta": {"role_preferences": {"coder": "codex"}},
        "gamma": {},
    }

    projects: dict[str, ProjectConfig] = {}
    for name, spec in project_specs.items():
        project_path = Path(spec.get("path", root / name))
        project_path.mkdir(parents=True, exist_ok=True)
        (project_path / "README.md").write_text("# Test project\n", encoding="utf-8")
        (project_path / "app.py").write_text("print('test')\n", encoding="utf-8")
        projects[name] = ProjectConfig(
            path=project_path,
            auto_restart=bool(spec.get("auto_restart", False)),
            restart_service=spec.get("restart_service", ""),
            commands=ProjectCommandsConfig(
                restart=spec.get("restart", ""),
                restart_shell=spec.get("restart_shell", "auto"),
                test=spec.get("test_command", ""),
                smoke=list(spec.get("smoke_commands", [])),
            ),
            pipeline=PipelineConfig(
                coder=spec.get("coder", ""),
                reviewers=list(spec.get("reviewers", [])),
                tester=spec.get("tester", ""),
                test_command=spec.get("pipeline_test_command", ""),
                lint_command=spec.get("pipeline_lint_command", ""),
                max_cycles=int(spec.get("max_cycles", 10)),
                auto_pr=bool(spec.get("auto_pr", True)),
                pr_tool=spec.get("pr_tool", "gh"),
                base_branch=spec.get("base_branch", "main"),
                plan_threshold=spec.get("plan_threshold", "complex"),
                push_remote=spec.get("push_remote", "origin"),
            ),
            role_preferences=dict(spec.get("role_preferences", {})),
        )

    def tool(cli_key: str, roles: list[str]) -> CLIToolConfig:
        extra_args = ["--skip-git-repo-check"] if cli_key == "codex" else []
        return CLIToolConfig(
            command=cli_commands.get(cli_key, command),
            base_args=[],
            autonomy_args=[],
            extra_args=extra_args,
            timeout=30,
            enabled=cli_key not in disabled_clis,
            roles=roles,
        )

    return Config(
        discord=DiscordConfig(token="x", owner_id=1, channel_id=None),
        llm=LLMConfig(
            primary=LLMProviderConfig(
                provider="minimax",
                base_url="https://api.minimaxi.com/anthropic",
                model="MiniMax-M2.7",
                api_key="",
            ),
            fallback=LLMProviderConfig(
                provider="ollama",
                base_url="http://localhost:11434/v1",
                model="qwen3.5:4b",
                api_key="ollama",
            ),
        ),
        cli=CLIConfig(
            claude_code=tool("claude_code", ["coder"]),
            codex=tool("codex", ["coder"]),
            gemini_cli=tool("gemini_cli", ["reviewer", "tester"]),
            qwen_cli=tool("qwen_cli", ["reviewer"]),
        ),
        shell=ShellConfig(default="auto", timeout=30, wsl_distro=None),
        todo=TodoConfig(
            file=todo_home / "todos.md",
            done_file=todo_home / "done.md",
            auto_start=False,
            busy_cli_timeout=30,
        ),
        context=ContextConfig(),
        reporter=ReporterConfig(),
        projects=projects,
        services=service_specs or {},
        pipeline=PipelineConfig(),
        team_roles={},
        workflows={},
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


class FakeResponse:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bool]] = []
        self.deferred = False

    async def send_message(self, content=None, *, ephemeral=False, embed=None, **_kwargs):
        if content is not None:
            payload = str(content)
        elif embed is not None:
            payload = f"<embed:{embed.title}>"
        else:
            payload = "<empty>"
        self.messages.append((payload, ephemeral))

    async def send(self, content=None, *, ephemeral=False, embed=None, **kwargs):
        await self.send_message(content, ephemeral=ephemeral, embed=embed, **kwargs)

    async def defer(self, *, ephemeral=False, thinking=False, **_kwargs):
        self.deferred = True
        self.messages.append((f"<deferred ephemeral={ephemeral} thinking={thinking}>", ephemeral))


class FakeUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id


class FakeInteraction:
    def __init__(self, user_id: int) -> None:
        self.user = FakeUser(user_id)
        self.response = FakeResponse()
        self.followup = self.response
