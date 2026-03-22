"""Global config loader — YAML with ${ENV_VAR} interpolation."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import platformdirs
import yaml
from dotenv import load_dotenv

load_dotenv()

_ENV_RE = re.compile(r"\$\{([^}]+)\}")


def _interpolate(value: str) -> str:
    """Replace ${VAR} with environment variable values."""
    return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)


def _walk(obj):
    """Recursively interpolate all string values in a dict/list."""
    if isinstance(obj, dict):
        return {k: _walk(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_walk(v) for v in obj]
    if isinstance(obj, str):
        return _interpolate(obj)
    return obj


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DiscordConfig:
    token: str
    owner_id: int
    channel_id: Optional[int] = None


@dataclass
class LLMProviderConfig:
    provider: str
    base_url: str
    model: str
    api_key: str = "ollama"


@dataclass
class LLMConfig:
    primary: LLMProviderConfig
    fallback: LLMProviderConfig


@dataclass
class CLIToolConfig:
    command: str
    base_args: list[str] = field(default_factory=list)
    autonomy_args: list[str] = field(default_factory=list)
    extra_args: list[str] = field(default_factory=list)
    timeout: int = 600
    enabled: bool = True
    roles: list[str] = field(default_factory=list)

    def build_args(self) -> list[str]:
        """Return base_args + autonomy_args + extra_args (before the task message)."""
        return self.base_args + self.autonomy_args + self.extra_args


@dataclass
class CLIConfig:
    claude_code: CLIToolConfig
    codex: CLIToolConfig
    gemini_cli: CLIToolConfig
    qwen_cli: CLIToolConfig


@dataclass
class ShellConfig:
    default: str = "auto"
    timeout: int = 300
    wsl_distro: Optional[str] = None


@dataclass
class ContextConfig:
    max_age_days: int = 7


@dataclass
class TodoConfig:
    file: Path = field(default_factory=lambda: Path("~/.devbot/todos.md").expanduser())
    done_file: Path = field(default_factory=lambda: Path("~/.devbot/done.md").expanduser())
    auto_start: bool = False
    busy_cli_timeout: int = 300


@dataclass
class ProjectDocsConfig:
    product: list[str] = field(default_factory=lambda: ["README.md"])
    architecture: list[str] = field(
        default_factory=lambda: [
            "ARCHITECTURE.md",
            "*architecture*.md",
            "docs/**/*architecture*.md",
            "docs/**/architecture*.md",
        ]
    )
    agent_context: list[str] = field(
        default_factory=lambda: ["CLAUDE.md", "AGENTS.md", "GEMINI.md"]
    )
    additional: list[str] = field(default_factory=list)


@dataclass
class ProjectCommandsConfig:
    install: str = ""
    test: str = ""
    smoke: list[str] = field(default_factory=list)
    run: str = ""
    restart: str = ""
    restart_shell: str = "auto"


@dataclass
class ProjectQAConfig:
    kind: str = "generic"
    smoke_commands: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)


@dataclass
class ProjectAnalysisConfig:
    entry_files: list[str] = field(default_factory=list)
    doc_globs: list[str] = field(default_factory=lambda: ["docs/**/*.md", "*.md"])
    preferred_reviewer_cli: str = ""


@dataclass
class PipelineConfig:
    coder: str = ""
    reviewers: list[str] = field(default_factory=list)
    tester: str = ""
    test_command: str = ""
    lint_command: str = ""
    max_cycles: int = 10
    auto_pr: bool = True
    pr_tool: str = "gh"
    base_branch: str = "main"
    plan_threshold: str = "complex"
    push_remote: str = "origin"


@dataclass
class ProjectConfig:
    path: Path
    description: str = ""
    type: str = "generic"
    auto_restart: bool = False
    restart_service: str = ""
    context_files: list[str] = field(
        default_factory=lambda: ["CLAUDE.md", "AGENTS.md", "GEMINI.md", "README.md"]
    )
    docs: ProjectDocsConfig = field(default_factory=ProjectDocsConfig)
    commands: ProjectCommandsConfig = field(default_factory=ProjectCommandsConfig)
    qa: ProjectQAConfig = field(default_factory=ProjectQAConfig)
    analysis: ProjectAnalysisConfig = field(default_factory=ProjectAnalysisConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    role_preferences: dict[str, str] = field(default_factory=dict)


@dataclass
class ServiceConfig:
    """A named service managed via shell commands (e.g. openclaw, nginx, redis)."""
    shell: str = "auto"          # which shell to use: auto | wsl | bash | powershell
    commands: dict[str, str] = field(default_factory=dict)   # start/stop/restart/status/logs


@dataclass
class ReporterConfig:
    stream_threshold: int = 30
    batch_interval: int = 15
    max_message_length: int = 1900


@dataclass
class Config:
    discord: DiscordConfig
    llm: LLMConfig
    cli: CLIConfig
    shell: ShellConfig
    todo: TodoConfig
    context: ContextConfig
    reporter: ReporterConfig
    projects: dict[str, ProjectConfig]
    services: dict[str, ServiceConfig] = field(default_factory=dict)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    team_roles: dict[str, dict[str, Any]] = field(default_factory=dict)
    workflows: dict[str, dict[str, Any]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _default_config_path() -> Path:
    config_dir = Path(platformdirs.user_config_dir("devbot"))
    return config_dir / "config.yaml"


def _parse_cli_tool(
    d: dict,
    default_cmd: str,
    default_base: list[str],
    default_autonomy: list[str],
    default_roles: list[str],
    default_extra: list[str] | None = None,
) -> CLIToolConfig:
    """Parse a CLI tool config supporting both new (base_args/autonomy_args) and old (args) format."""
    command = d.get("command", default_cmd)
    enabled = d.get("enabled", True)
    timeout = d.get("timeout", 600)
    roles = d.get("roles", default_roles)
    extra_raw = d.get("extra_args")
    if extra_raw is None:
        extra_args = list(default_extra or [])
    else:
        extra_args = [str(v) for v in extra_raw]
        if not extra_args and default_extra:
            extra_args = list(default_extra)

    if "base_args" in d:
        # New format
        base_args = d.get("base_args", default_base)
        autonomy_args = d.get("autonomy_args", default_autonomy)
    else:
        # Old format: split legacy "args" into autonomy_args, base_args gets defaults
        legacy_args = d.get("args", [])
        base_args = default_base
        autonomy_args = legacy_args if legacy_args else default_autonomy

    return CLIToolConfig(
        command=command,
        base_args=base_args,
        autonomy_args=autonomy_args,
        extra_args=extra_args,
        timeout=timeout,
        enabled=enabled,
        roles=roles,
    )


def _ensure_str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [value]
    return []


def _parse_pipeline_config(data: dict[str, Any] | None, fallback: PipelineConfig | None = None) -> PipelineConfig:
    base = fallback or PipelineConfig()
    raw = data or {}
    reviewers = _ensure_str_list(raw.get("reviewers"))
    return PipelineConfig(
        coder=str(raw.get("coder", base.coder)),
        reviewers=reviewers or list(base.reviewers),
        tester=str(raw.get("tester", base.tester)),
        test_command=str(raw.get("test_command", base.test_command)),
        lint_command=str(raw.get("lint_command", base.lint_command)),
        max_cycles=max(1, int(raw.get("max_cycles", base.max_cycles))),
        auto_pr=bool(raw.get("auto_pr", base.auto_pr)),
        pr_tool=str(raw.get("pr_tool", base.pr_tool)),
        base_branch=str(raw.get("base_branch", base.base_branch)),
        plan_threshold=str(raw.get("plan_threshold", base.plan_threshold)),
        push_remote=str(raw.get("push_remote", base.push_remote)),
    )


def load_config(path: Optional[Path] = None) -> Config:
    config_path = path or _default_config_path()

    if not config_path.exists():
        raise FileNotFoundError(
            f"Config not found at {config_path}. "
            f"Run `devbot init` or copy devbot/config/default_config.yaml there."
        )

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    data = _walk(raw)

    # Discord — support both top-level and messaging.discord
    messaging = data.get("messaging", {})
    d = data.get("discord") or messaging.get("discord", {})
    owner_id_raw = d.get("owner_id", "")
    channel_id_raw = d.get("channel_id", "")
    discord_cfg = DiscordConfig(
        token=d.get("token", ""),
        owner_id=int(owner_id_raw) if owner_id_raw else 0,
        channel_id=int(channel_id_raw) if channel_id_raw else None,
    )

    # LLM
    llm_data = data.get("llm", {})
    primary_data = llm_data.get("primary", {})
    fallback_data = llm_data.get("fallback", {})
    llm_cfg = LLMConfig(
        primary=LLMProviderConfig(
            provider=primary_data.get("provider", "minimax"),
            base_url=primary_data.get("base_url", ""),
            model=primary_data.get("model", ""),
            api_key=primary_data.get("api_key", ""),
        ),
        fallback=LLMProviderConfig(
            provider=fallback_data.get("provider", "ollama"),
            base_url=fallback_data.get("base_url", "http://localhost:11434/v1"),
            model=fallback_data.get("model", "qwen2.5:14b"),
            api_key="ollama",
        ),
    )

    # CLI tools
    cli_data = data.get("cli", {})
    cli_cfg = CLIConfig(
        claude_code=_parse_cli_tool(
            cli_data.get("claude_code", {}), "claude",
            default_base=["-p", "--output-format", "stream-json"],
            default_autonomy=["--dangerously-skip-permissions"],
            default_roles=["coder"],
            default_extra=[],
        ),
        codex=_parse_cli_tool(
            cli_data.get("codex", {}), "codex",
            default_base=["exec", "--json"],
            default_autonomy=["--full-auto"],
            default_roles=["coder"],
            default_extra=["--skip-git-repo-check"],
        ),
        gemini_cli=_parse_cli_tool(
            cli_data.get("gemini_cli", {}), "gemini",
            default_base=["-p", "--output-format", "stream-json"],
            default_autonomy=["--yolo"],
            default_roles=["reviewer", "tester"],
            default_extra=[],
        ),
        qwen_cli=_parse_cli_tool(
            cli_data.get("qwen_cli", {}), "qwen",
            default_base=["-p", "--output-format", "stream-json"],
            default_autonomy=["--yolo"],
            default_roles=["reviewer"],
            default_extra=[],
        ),
    )

    # Shell
    shell_data = data.get("shell", {})
    shell_cfg = ShellConfig(
        default=shell_data.get("default", "auto"),
        timeout=shell_data.get("timeout", 300),
        wsl_distro=shell_data.get("wsl_distro") or None,
    )

    todo_data = data.get("todo", {})
    todo_cfg = TodoConfig(
        file=Path(str(todo_data.get("file", "~/.devbot/todos.md"))).expanduser(),
        done_file=Path(str(todo_data.get("done_file", "~/.devbot/done.md"))).expanduser(),
        auto_start=bool(todo_data.get("auto_start", False)),
        busy_cli_timeout=int(todo_data.get("busy_cli_timeout", 300)),
    )

    # Context
    context_data = data.get("context", {})
    context_cfg = ContextConfig(
        max_age_days=context_data.get("max_age_days", 7),
    )

    pipeline_cfg = _parse_pipeline_config(data.get("pipeline"))

    # Reporter — also check legacy "execution" key
    exec_data = data.get("reporter") or data.get("execution", {})
    reporter_cfg = ReporterConfig(
        stream_threshold=exec_data.get("stream_threshold") or exec_data.get("stream_batch_threshold", 30),
        batch_interval=exec_data.get("batch_interval") or exec_data.get("stream_batch_interval", 15),
        max_message_length=exec_data.get("max_message_length", 1900),
    )

    # Projects
    projects: dict[str, ProjectConfig] = {}
    for name, pdata in (data.get("projects") or {}).items():
        docs_data = pdata.get("docs", {})
        commands_data = pdata.get("commands", {})
        qa_data = pdata.get("qa", {})
        analysis_data = pdata.get("analysis", {})
        role_preferences = pdata.get("role_preferences") or pdata.get("roles") or {}

        projects[name] = ProjectConfig(
            path=Path(pdata["path"]),
            description=pdata.get("description", ""),
            type=pdata.get("type", "generic"),
            auto_restart=bool(pdata.get("auto_restart", False)),
            restart_service=str(pdata.get("restart_service", "")),
            context_files=pdata.get(
                "context_files",
                ["CLAUDE.md", "AGENTS.md", "GEMINI.md", "README.md"],
            ),
            docs=ProjectDocsConfig(
                product=_ensure_str_list(docs_data.get("product")) or ["README.md"],
                architecture=_ensure_str_list(docs_data.get("architecture")) or [
                    "ARCHITECTURE.md",
                    "*architecture*.md",
                    "docs/**/*architecture*.md",
                    "docs/**/architecture*.md",
                ],
                agent_context=_ensure_str_list(docs_data.get("agent_context")) or [
                    "CLAUDE.md",
                    "AGENTS.md",
                    "GEMINI.md",
                ],
                additional=_ensure_str_list(docs_data.get("additional")),
            ),
            commands=ProjectCommandsConfig(
                install=str(commands_data.get("install", "")),
                test=str(commands_data.get("test", "")),
                smoke=_ensure_str_list(commands_data.get("smoke")),
                run=str(commands_data.get("run", "")),
                restart=str(commands_data.get("restart", "")),
                restart_shell=str(commands_data.get("restart_shell", "auto")),
            ),
            qa=ProjectQAConfig(
                kind=str(qa_data.get("kind", "generic")),
                smoke_commands=_ensure_str_list(qa_data.get("smoke_commands")),
                targets=_ensure_str_list(qa_data.get("targets")),
            ),
            analysis=ProjectAnalysisConfig(
                entry_files=_ensure_str_list(analysis_data.get("entry_files")),
                doc_globs=_ensure_str_list(analysis_data.get("doc_globs")) or ["docs/**/*.md", "*.md"],
                preferred_reviewer_cli=str(analysis_data.get("preferred_reviewer_cli", "")),
            ),
            pipeline=_parse_pipeline_config(pdata.get("pipeline"), fallback=pipeline_cfg),
            role_preferences={
                str(k): str(v)
                for k, v in role_preferences.items()
                if str(k).strip() and str(v).strip()
            },
        )

    # Services
    services: dict[str, ServiceConfig] = {}
    for name, sdata in (data.get("services") or {}).items():
        services[name] = ServiceConfig(
            shell=sdata.get("shell", "auto"),
            commands=sdata.get("commands", {}),
        )

    return Config(
        discord=discord_cfg,
        llm=llm_cfg,
        cli=cli_cfg,
        shell=shell_cfg,
        todo=todo_cfg,
        context=context_cfg,
        reporter=reporter_cfg,
        projects=projects,
        services=services,
        pipeline=pipeline_cfg,
        team_roles=data.get("team_roles") or {},
        workflows=data.get("workflows") or {},
    )
