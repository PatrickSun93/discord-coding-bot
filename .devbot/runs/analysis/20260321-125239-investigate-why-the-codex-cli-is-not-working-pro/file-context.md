=== CLAUDE.md ===
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Environment

**Conda environment**: `devbot` (Python 3.11)

```bash
conda activate devbot

# Install / reinstall after adding dependencies
pip install -e .

# Run the bot
devbot start

# First-time setup
devbot init       # interactive wizard -- writes config to %LOCALAPPDATA%\devbot\devbot\config.yaml
devbot doctor     # validate CLIs, shells, config, Ollama, Discord token

# Smoke tests (no network needed)
python smoke_test.py    # imports + adapter logic + blocklist + platform detection
python test_runner.py   # async subprocess runner
```

The config path on this Windows machine is:
`C:\Users\peido\AppData\Local\devbot\devbot\config.yaml`

Installed CLIs: `claude` (Claude Code), `qwen`, `gemini`. Ollama is running locally. WSL is available.

## Project Status

**Architecture**: v4.3 (`devbot-architecture-v4-final.md`)

Core foundation is implemented:
- Discord bot + owner auth + busy gate
- shell executor + blocklist + WSL/platform detection
- MiniMax/Ollama router
- all 4 CLI adapters
- task history + slash commands
- generic `read_files` + `analyze_project` tools
- data-driven project profiles, role registry, and workflow registry

Full multi-stage gstack-style orchestration is **not** fully automated yet. The repo now has the extensible foundation for that work.

| Phase | Status | Contents |
|-------|--------|----------|
| 1 Foundation | done | config, Discord bot, project registry |
| 2 Shell Execution | done | shell executor, blocklist, WSL, platform detection |
| 3 LLM Router | done | MiniMax + Ollama, dynamic system prompt, 7 tools |
| 4 CLI Agents | done | all 4 adapters, stream-JSON parser, Codex |
| 5 Project Mgmt | in progress | project profiles, role/workflow registry, run artifacts |
| 6 Review Pipeline | next | branch/code/review/test/push/PR loop |
| 7 Todo Queue | next | todos.md, parallel dispatch, !todo commands |
| 8 Harness | next | doc gardening, skills system, usage management |

## Architecture

DevBot is a Discord bot that routes natural language messages to coding, shell, file-read, or project-analysis tools.
A **router LLM** (MiniMax primary, Ollama fallback) classifies intent and dispatches to the right executor.

```
Discord Message
  |
  v
DevBotClient.on_message  (owner auth + busy check + react 👀)
  |
  v
LLMRouter.route()  (MiniMax -> Ollama fallback, dynamic system prompt)
  |
  +--[run_cli]-----> TaskManager.execute() -> CLI Adapter -> run_subprocess()
  |                      stream-JSON parser -> DiscordStreamer -> Discord
  |
  +--[run_shell]---> blocklist check -> run_shell() -> Discord reply
  |
  +--[read_context / read_files] -> project docs/files -> Discord reply
  |
  +--[analyze_project] -> role-aware prompt builder -> reviewer CLI -> persisted run artifacts
  |
  +--[list_projects / ask_clarification / reply] -> Discord reply
  |
  v
React emoji on original message (OK / error / question)
```

## Module Structure

```
devbot/
├── config/
│   ├── settings.py          # YAML + ${ENV_VAR} interpolation, typed dataclasses
│   └── default_config.yaml  # Template (v4 format)
├── bot/
│   ├── client.py            # DevBotClient: on_message -> LLM -> dispatch; reaction helpers
│   ├── commands.py          # Slash commands: /status /cancel /projects /project /config
│   │                        #   /history /shells /doctor
│   └── formatter.py         # format_project_list, format_status
├── llm/
│   ├── router.py            # LLMRouter: MiniMax -> Ollama fallback, returns ToolDecision
│   └── tools_schema.py      # Tool defs (ANTHROPIC_TOOLS + TOOLS) + build_system_prompt()
├── workflow/
│   ├── default_roles.yaml   # Packaged default role registry
│   ├── default_workflows.yaml  # Packaged default workflow registry
│   ├── prompts.py           # Prompt builders for role-based work
│   ├── registry.py          # Load/merge role + workflow registries
│   └── store.py             # Persist run artifacts under .devbot/runs/
├── executor/
│   ├── manager.py           # TaskManager: single-task gate, run, cancel, returns TaskResult
│   ├── runner.py            # run_subprocess + kill_process (cross-platform)
│   ├── stream.py            # DiscordStreamer: real-time (<30s) -> batched (>30s)
│   ├── stream_parser.py     # Universal NDJSON parser for CLI stream-json output
│   ├── adapters/
│   │   ├── base.py          # BaseCLIAdapter ABC: build_command(task, project_path)
│   │   ├── claude_code.py   # claude -p --output-format stream-json --dangerously-skip-permissions
│   │   ├── codex.py         # codex exec --json --full-auto
│   │   ├── gemini_cli.py    # gemini -p --output-format stream-json --yolo
│   │   └── qwen_cli.py      # qwen -p --output-format stream-json --yolo
│   └── shell/
│       ├── __init__.py      # re-exports: is_command_blocked, run_shell, detect_platform
│       ├── platform.py      # detect_platform(), resolve_shell(), windows_path_to_wsl()
│       ├── blocklist.py     # BLOCKED_PATTERNS + is_command_blocked()
│       └── executor.py      # run_shell() -> ShellResult
├── context/
│   ├── project.py           # resolve_project: name or absolute path -> (path, display_name)
│   ├── loader.py            # load_project_context: reads core context files
│   └── files.py             # bounded file discovery + analysis file selection
├── history.py               # SQLite task history: record_task(), get_recent()
├── cli.py                   # devbot init / doctor / start entry points (ASCII only -- no emojis)
└── main.py                  # load_config -> DevBotClient -> asyncio.run
```

## Key Design Rules

- **Single task at a time** -- `task_manager.is_busy()` gates all incoming requests
- **Single-user auth** -- only Discord messages from `config.discord.owner_id` are processed
- **Never use `shell=True`** -- always `asyncio.create_subprocess_exec(*cmd_list)`
- **Cross-platform paths** -- `pathlib.Path` everywhere; `shutil.which()` for binary detection
- **Process termination** -- `terminate()` -> 5s wait -> `kill()` (Unix) / `taskkill /F /PID` (Windows)
- **No emojis or non-ASCII in `cli.py` output** -- Windows cp1252 terminal; use `[OK]`/`[FAIL]`
- **No non-ASCII in system prompt strings** -- same reason; use `->` not `->`, `--` not `--`
- **Emoji reactions on messages** -- 👀 on receipt, then ✅/❌/🤔 on completion; all via `_react()` helper
- **CLI command format** -- `[cmd] + base_args + autonomy_args + extra_args + [task]`
- **Stream-JSON output** -- all CLIs run with `--output-format stream-json`; `stream_parser.py` decodes NDJSON to plain text before Discord display

## CLI Agents

Command format per adapter: `[command] + base_args + autonomy_args + extra_args + [task]`

| CLI | Command built |
|-----|---------------|
| claude_code | `claude -p --output-format stream-json --dangerously-skip-permissions <task>` |
| codex | `codex exec --json --full-auto <task>` |
| gemini_cli | `gemini -p --output-format stream-json --yolo <task>` |
| qwen_cli | `qwen -p --output-format stream-json --yolo <task>` |

Adapter roles (used by LLM router to pick best fit):
- **Coders**: `claude_code`, `codex`
- **Reviewers/Testers**: `gemini_cli`, `qwen_cli`

## LLM Router

`LLMRouter.route(user_message)` -> `ToolDecision(tool, args)`.

**Five tools**: `run_cli`, `run_shell`, `read_context`, `ask_clarification`, `list_projects`.

**System prompt** is built dynamically by `build_system_prompt(config)` and includes:
- Host OS, available shells, installed CLIs
- Registered projects list
- Services table (name -> shell -> commands lookup)
- Intent-to-tool mapping table (OPERATIONAL / CODE TASK / READ DOCS / LIST / AMBIGUOUS / CHAT)

Routing strategy is **intent-first**: the LLM classifies intent by keyword signals before picking a tool. This avoids name-collision bugs (e.g. "openclaw" matching both a project and a service).

- **MiniMax**: Anthropic SDK (sync), wrapped in `loop.run_in_executor()`. Tools as `ANTHROPIC_TOOLS`.
- **Ollama**: `AsyncOpenAI(base_url=http://localhost:11434/v1)`. Tools as `TOOLS` (OpenAI format). 60s timeout.

## Shell Execution

`executor/shell/` handles all non-CLI command execution:

- **`detect_platform()`** -- detects OS, enumerates available shells, sets default (WSL on Windows if available)
- **`resolve_shell(shell, platform_info)`** -- returns `(cmd_prefix, is_wsl)` for subprocess building
- **`is_command_blocked(command)`** -- checks against `BLOCKED_PATTERNS` (rm, dd, mkfs, chmod 777, shutdown, etc.), returns `(blocked, reason)`
- **`run_shell(command, shell, working_dir, timeout)`** -- async, merges stdout+stderr, returns `ShellResult`
- **WSL path conversion** -- `windows_path_to_wsl("C:\\x")` -> `"/mnt/c/x"` applied automatically when `is_wsl=True`

Blocked commands are refused with a Discord message; never silently dropped.

## Configuration (v4)

Config path: `platformdirs.user_config_dir("devbot")` + `/config.yaml`.
Supports `${ENV_VAR}` interpolation. Per-project `.devbot.yaml` can override `context_files`.

Top-level sections:

```yaml
discord:   token, owner_id, channel_id
llm:       primary (MiniMax), fallback (Ollama)
cli:       claude_code, codex, gemini_cli, qwen_cli
           each has: command, base_args, autonomy_args, extra_args, timeout, enabled, roles
shell:     default, timeout, wsl_distro
services:  <name>: {shell, commands: {start, stop, restart, status, logs}}
context:   max_age_days
reporter:  stream_threshold, batch_interval, max_message_length
projects:  <name>: {path, description, context_files}
```

The loader is backward-compatible: old configs using `args` (instead of `base_args`/`autonomy_args`) still load correctly.

## Streaming

`DiscordStreamer` receives lines from `run_subprocess` via the `stream_parser` wrapper:

1. `run_subprocess()` calls `on_output(raw_line)` for each stdout/stderr line
2. `make_json_output_handler(streamer.on_output)` wraps it: parses NDJSON events, extracts text, falls back to plain text for non-JSON lines
3. `DiscordStreamer` adapts:
   - **0-30s**: edits a single Discord message with the last 15 output lines
   - **>30s**: posts batch summaries every 15s
   - **On finish**: `send_result()` posts a rich embed; `TaskManager.execute()` returns the returncode

## Discord Reactions

`client.py` uses three helpers: `_react(message, emoji)`, `_clear_reaction(message, emoji, me)`.

| State | Reaction |
|-------|----------|
| Message received, routing | 👀 |
| Task/shell success | 👀 removed, ✅ added |
| Task/shell failure | 👀 removed, ❌ added |
| Clarification asked | 👀 removed, 🤔 added |
| Project/CLI not found | 👀 removed, ❌ added |

All reaction calls are try/except -- missing `Add Reactions` permission does not crash the bot.

## Slash Commands

| Command | Description |
|---------|-------------|
| `/status` | Show running task info |
| `/cancel` | Kill running task |
| `/projects` | List registered projects |
| `/project add <name> <path>` | Register a project (in-memory) |
| `/config reload` | Hot-reload config from disk |
| `/history` | Last 10 tasks from SQLite history |
| `/shells` | OS + available shells + default |
| `/doctor` | Check CLIs, gh, docker, WSL inline |

## Dependencies

```
discord.py>=2.3
anthropic>=0.40    # MiniMax via Anthropic SDK (sync, thread-pool-wrapped)
openai>=1.0        # Ollama via OpenAI-compat (async)
httpx>=0.27
pyyaml>=6.0
platformdirs>=4.0
python-dotenv>=1.0
```

## Legacy Node.js Implementation

A separate minimal Node.js/CommonJS implementation exists under `src/` (entry: `src/index.js`).
It uses `discord.js` and has basic backends (`src/backends/cli.js`, `codex.js`, `gemini.js`).
This is an older parallel codebase — **the Python `devbot/` package is the primary implementation**.
Do not confuse the two; `package.json` / `node_modules` belong to this legacy layer only.


=== README.md ===

# DevBot — Discord AI Development Assistant

DevBot is a self-hosted Discord bot that acts as an AI-powered coding assistant. Send a natural language message in Discord; a router LLM (MiniMax, with Ollama fallback) interprets your intent, picks the right tool, and runs it against your local projects. Output streams back to Discord in real time.

```
You (Discord) ──► DevBot ──► MiniMax/Ollama (Router LLM)
                    │                  │
                    │          tool-call decision
                    │                  │
                    ▼                  ▼
              CLI Executor ──► claude / qwen / gemini
                    │
                    ▼
              Discord Channel (progress + results)
```

## Features

- Routes messages to coding, shell, file-read, or analysis tools based on task type
- Real-time output streaming: live edits for short tasks, batched summaries for long ones
- Rich Discord embeds for task results (exit code, duration, output summary)
- Extensible project profiles: docs, commands, QA targets, analysis hints, role preferences
- Data-driven team registry: roles and workflows are loaded from config plus packaged defaults
- Slash commands: `/status`, `/cancel`, `/projects`, `/project add`, `/config reload`, `/history`, `/roles`, `/workflows`
- SQLite task history via `/history`
- Single-user auth (owner ID gate) and optional channel restriction
- Cross-platform: Windows, macOS, Linux
- `devbot init` setup wizard and `devbot doctor` validation command

## Requirements

- Python 3.11+
- At least one AI CLI installed and on `PATH`:
  - [Claude Code](https://claude.ai/code) (`claude`)
  - [Qwen CLI](https://github.com/QwenLM/qwen-agent) (`qwen`)
  - [Gemini CLI](https://github.com/google-gemini/gemini-cli) (`gemini`)
- [Ollama](https://ollama.com/) running locally (for the fallback router)
- A Discord bot token and your Discord user ID

## Installation

```bash
git clone https://github.com/your-username/discord-coding-bot
cd discord-coding-bot
conda create -n devbot python=3.11 -y
conda activate devbot
pip install -e .
```

## Setup

```bash
# Interactive setup wizard — writes config to the platform config dir
devbot init

# Validate everything (CLIs, config, Ollama, Discord token)
devbot doctor
```

The config file is written to:

| Platform | Path |
|----------|------|
| Windows  | `%LOCALAPPDATA%\devbot\devbot\config.yaml` |
| macOS    | `~/Library/Application Support/devbot/config.yaml` |
| Linux    | `~/.config/devbot/config.yaml` |

### Manual config

Copy `devbot/config/default_config.yaml` to the platform path above and fill in your values:

```yaml
discord:
  token: "${DISCORD_BOT_TOKEN}"      # or paste the token directly
  owner_id: "123456789012345678"     # your Discord user ID
  channel_id: ""                     # optional: restrict to one channel

llm:
  primary:
    provider: "minimax"
    base_url: "https://api.minimaxi.com/anthropic"
    api_key: "${MINIMAX_API_KEY}"
    model: "MiniMax-M2.7"
  fallback:
    provider: "ollama"
    base_url: "http://localhost:11434/v1"
    model: "qwen3.5:4b"

projects:
  backend:
    path: "/home/user/projects/backend"
    type: "api"
    description: "Main backend API"
    docs:
      product: ["README.md", "docs/product/**/*.md"]
      architecture: ["ARCHITECTURE.md", "docs/architecture/**/*.md"]
      agent_context: ["CLAUDE.md", "AGENTS.md", "GEMINI.md"]
    commands:
      test: "pytest -q"
    analysis:
      entry_files: ["ARCHITECTURE.md"]
      preferred_reviewer_cli: "gemini_cli"
    role_preferences:
      coder: "claude_code"
      reviewer: "qwen_cli"
```

## Usage

```bash
devbot start
```

Then in Discord:

```
> add input validation to the registration endpoint in project backend
> use gemini to review the auth module in /home/me/api for security issues
> analyze the workflow design for project backend using ARCHITECTURE.md
> read docs/architecture/current-state.md in project backend
> list projects
> /cancel
> /status
> /history
```

### Slash commands

| Command | Description |
|---------|-------------|
| `/status` | Show current task (CLI, elapsed time, line count) |
| `/cancel` | Cancel the running task |
| `/projects` | List registered projects |
| `/project add <name> <path>` | Register a new project |
| `/config reload` | Hot-reload config from disk |
| `/history` | Show the last 10 tasks |
| `/roles` | List workflow roles and preferred CLIs |
| `/workflows` | List workflow definitions |

### Per-project overrides

Create `.devbot.yaml` in a project directory to customise context files or analysis entry files:

```yaml
context_files: ["claude.md", "docs/ARCHITECTURE.md"]
analysis:
  entry_files: ["docs/ARCHITECTURE.md", "docs/current-workflow.md"]
```

### Project Profiles

Projects are now first-class profiles instead of just paths. Each project can declare:

- `docs`: product, architecture, and agent-context document globs
- `commands`: install, test, smoke, and run commands
- `qa`: QA kind plus smoke commands or targets
- `analysis`: entry files and reviewer preferences
- `role_preferences`: which CLI should act as planner, coder, reviewer, and so on

This lets DevBot stay generic across repos while still giving the router and reviewer roles enough structure to work predictably.

### Team Roles And Workflows

DevBot ships with default roles such as `planner`, `coder`, `reviewer`, `qa`, `release`, and `investigator`, plus workflows like `analysis`, `code_review`, `investigation`, and `feature_delivery`.

You can extend them in config:

```yaml
team_roles:
  security_reviewer:
    purpose: "Audit security-sensitive changes."
    capabilities: ["security", "review"]
    preferred_clis: ["gemini_cli", "qwen_cli"]
    inputs: ["diff", "plan", "project_context"]
    outputs: ["security_report"]
    allowed_tools: ["read_files", "analyze_project"]

workflows:
  security_audit:
    description: "Security-first project audit."
    stages: ["security_reviewer", "qa"]
    default_entry_role: "security_reviewer"
```

## Architecture

```
devbot/
├── config/           # YAML loader, env var interpolation, typed dataclasses
├── bot/              # Discord client, slash commands, message formatter
├── llm/              # LLM router (MiniMax primary, Ollama fallback) + tool schema
├── workflow/         # Role registry, workflow registry, prompt builders, run artifacts
├── executor/         # Task manager, subprocess runner, adaptive Discord streamer
│   └── adapters/     # BaseCLIAdapter + Claude Code / Qwen / Gemini adapters
├── context/          # Project registry, file discovery, context loaders
├── history.py        # SQLite task history
├── cli.py            # devbot init / doctor / start entry points
└── main.py           # Bot entry point
```

See [devbot-architecture-v4-final.md](devbot-architecture-v4-final.md) for the full design document.

## Smoke tests

```bash
python smoke_test.py    # imports + adapter logic (no network)
python test_runner.py   # async subprocess runner (no network)
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).


=== docs/readme/README.es.md ===
# Discord Coding Bot

> Idiomas: [English](../../README.md) | [简体中文](README.zh-CN.md) | **Español**

Un bot de Discord para enrutar mensajes a backends de programación como **Codex** y **Gemini CLI**.

## Estado actual

Este es un scaffold simple con salida progresiva en Discord.

Backends compatibles:
- `codex`
- `gemini`

## Comandos

- `!help`
- `!backend`
- `!backend codex`
- `!backend gemini`
- `!pwd`
- `!cd <path>`

Cualquier mensaje que no sea un comando se envía al backend seleccionado.

## Configuración

1. Copia el archivo de entorno:

```bash
cp .env.example .env
```

2. Completa:
- `DISCORD_BOT_TOKEN`
- `DISCORD_CHANNEL_ID` opcional
- `DEFAULT_BACKEND`
- `DEFAULT_WORKDIR`
- `CODEX_CMD`
- `CODEX_ARGS` opcional (por defecto: `exec --full-auto`)
- `GEMINI_CMD`

3. Instala dependencias:

```bash
npm install
```

4. Ejecuta:

```bash
npm start
```

## Notas

- La invocación de backends está abstraída en `src/backends/`.
- La salida progresiva en Discord usa lógica compartida de streaming por CLI y ediciones de mensajes con throttling.
- Las respuestas largas se dividen en varios mensajes de Discord cuando hace falta.
- El streaming actual está basado en fragmentos de stdout, no en token streaming.
- La experiencia de streaming depende de cómo el CLI del backend emita stdout. Si el backend solo imprime al final, el usuario seguirá viendo una respuesta final en lugar de progreso real.
- Codex usa por defecto `codex exec --full-auto <prompt>` para una invocación no interactiva más práctica.
- Codex verifica que el directorio de trabajo esté dentro de un repositorio git antes de ejecutarse, porque normalmente espera un contexto de repo confiable.

## Documentación multilingüe

- El `README.md` raíz es la fuente principal.
- Las traducciones viven en `docs/readme/`.
- Cuando cambie el comportamiento, primero actualiza el README en inglés y luego sincroniza las traducciones.

## Próximos pasos razonables

- manejo de argumentos específicos por backend
- persistencia de sesiones
- mejor integración con Codex CLI
- adaptador de Claude Code si hace falta
- streaming opcional de stderr / estado


=== docs/readme/README.zh-CN.md ===
# Discord Coding Bot

> 语言： [English](../../README.md) | **简体中文** | [Español](README.es.md)

一个用于将 Discord 消息路由到 **Codex** 和 **Gemini CLI** 等编码后端的机器人脚手架。

## 当前状态

这是一个带有渐进式 Discord 输出的简洁脚手架。

支持的后端切换：
- `codex`
- `gemini`

## 命令

- `!help`
- `!backend`
- `!backend codex`
- `!backend gemini`
- `!pwd`
- `!cd <path>`

所有非命令消息都会被转发到当前选定的后端。

## 配置

1. 复制环境变量文件：

```bash
cp .env.example .env
```

2. 填写以下配置：
- `DISCORD_BOT_TOKEN`
- 可选的 `DISCORD_CHANNEL_ID`
- `DEFAULT_BACKEND`
- `DEFAULT_WORKDIR`
- `CODEX_CMD`
- 可选的 `CODEX_ARGS`（默认值为 `exec --full-auto`）
- `GEMINI_CMD`

3. 安装依赖：

```bash
npm install
```

4. 运行：

```bash
npm start
```

## 说明

- 后端调用逻辑被抽象在 `src/backends/` 下。
- 渐进式 Discord 输出基于共享 CLI 流式逻辑和节流后的消息编辑实现。
- 长输出会在需要时拆分成多条 Discord 消息。
- 当前流式能力基于 stdout 分块输出，不是 token 级流式。
- 最终看起来是否“真的在流式输出”，取决于后端 CLI 如何输出 stdout。如果后端只在最后一次性输出，用户看到的仍然会接近最终一次性回复。
- Codex 默认使用 `codex exec --full-auto <prompt>`，适合非交互式调用。
- Codex 在启动前会检查当前工作目录是否位于 git 仓库内，因为 Codex 通常依赖受信任的仓库上下文。

## 多语言文档

- 根目录下的 `README.md` 是主版本。
- 翻译文件放在 `docs/readme/` 目录中。
- 当行为发生变化时，先更新英文 README，再同步翻译内容。

## 后续可做

- 后端特定参数处理
- 会话持久化
- 更好的 Codex CLI 集成
- 如有需要，增加 Claude Code 适配器
- 可选的 stderr / 状态流输出


=== CONTRIBUTING.md ===
# Contributing to DevBot

Thank you for your interest in contributing!

## Development setup

```bash
git clone https://github.com/your-username/discord-coding-bot
cd discord-coding-bot
conda create -n devbot python=3.11 -y
conda activate devbot
pip install -e .
```

## Smoke tests

Before submitting a PR, run the smoke tests (no network or Discord token needed):

```bash
python smoke_test.py    # imports + adapter logic
python test_runner.py   # async subprocess runner
```

## Code style

- Python 3.11+, standard library + dependencies in `pyproject.toml`
- `pathlib.Path` for all paths; never `shell=True` in subprocesses
- Keep the single-task gate (`task_manager.is_busy()`) intact — it exists to prevent race conditions on the filesystem
- No emojis in `cli.py` output (Windows cp1252 terminal limitation); use ASCII `[OK]`/`[FAIL]`

## Project structure

The architecture is documented in [devbot-architecture.md](devbot-architecture.md). Key modules:

| Module | Responsibility |
|--------|---------------|
| `devbot/bot/` | Discord client and slash commands |
| `devbot/llm/` | LLM router (MiniMax + Ollama fallback) |
| `devbot/executor/` | Subprocess management and Discord streaming |
| `devbot/context/` | Project registry and context file loading |
| `devbot/config/` | YAML config loader with env var interpolation |

## Submitting changes

1. Fork the repo and create a branch from `main`
2. Make your changes, keeping PRs focused on one concern
3. Ensure `smoke_test.py` and `test_runner.py` pass
4. Open a pull request with a clear description of what changed and why

## Reporting issues

Please open a GitHub issue with:
- What you expected to happen
- What actually happened
- Your OS, Python version, and which CLIs are installed (`devbot doctor` output is helpful)


=== devbot-architecture-v4-final.md ===
# DevBot — AI Development Assistant

## Final Architecture Document v4.3

---

## 1. Overview

**DevBot** is a cross-platform AI development assistant accessed via messaging platforms. You talk to it in Discord (or Telegram, Slack, MS Teams — see Section 21); it codes, reviews, tests, runs commands, and manages projects on your local machine.

### Core Capabilities

| # | Capability | Description |
|---|-----------|-------------|
| 1 | **Chat** | Answer questions, explain errors, discuss approaches via MiniMax / Ollama |
| 2 | **CLI Agents** | Dispatch coding tasks to Claude Code, Codex, Gemini CLI, or Qwen CLI |
| 3 | **Shell Execution** | Run commands on the host (bash/zsh/WSL/PowerShell) with a safety blocklist |
| 4 | **Todo Queue** | Process prioritized task lists — parallel across CLIs |
| 5 | **Review Pipeline** | Code → Review → Fix loop → Test → Push → PR (fully automatic) |
| 6 | **Project Management** | Scaffolding, dev containers, context file auto-refresh, project registry |
| 7 | **Harness Engineering** | Structured knowledge base, linter enforcement, doc gardening, execution plans |
| 8 | **Shared Skills** | Reusable SKILL.md instructions shared across all CLIs |
| 9 | **Usage Management** | Rate limit detection, session pause/resume, usage tracking + reports |

```
You (Discord / Telegram / Slack / Teams)
  │
  ▼
Message Provider (abstract interface)
  │
  ▼
DevBot Core (Python)
  │
  ├──► MiniMax / Ollama (Router LLM) ──► decides action
  │
  ├──► CLI Agents (parallel, one task per CLI)
  │      ├── Claude Code    (-p --dangerously-skip-permissions --output-format stream-json)
  │      ├── Codex          (exec --full-auto --json)
  │      ├── Gemini CLI     (-p --yolo --output-format stream-json)
  │      └── Qwen CLI       (-p --yolo --output-format stream-json)
  │
  ├──► Shell Executor (bash / zsh / WSL / PowerShell)
  │      ├── Command blocklist (rm, dd, mkfs, chmod 777, shutdown...)
  │      └── OpenClaw management (start/stop/restart/status via WSL)
  │
  ├──► Review Pipeline
  │      branch → code → commit → review → fix loop → test → push → PR
  │
  ├──► Todo Queue
  │      todos.md → parse → validate → parallel dispatch → done.md
  │
  └──► Project Manager
         scaffolding → devcontainer → git init → /init → context refresh
```

### Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python | Simpler, good async, cross-platform |
| LLM Router | MiniMax (OpenAI-compat) + Ollama fallback | Cost-effective, offline fallback |
| Ad-hoc concurrency | Single task | Safer for one-off commands |
| Todo/Pipeline concurrency | Parallel across CLIs (1 per CLI) | Maximize throughput |
| Cross-platform | Windows (WSL+native) / macOS / Linux | Auto-detect, allow override |
| Auth | Single-user (owner ID) | Full trust, open-source ready |
| CLI permissions | All fully autonomous | `--dangerously-skip-permissions` / `--yolo` / `--full-auto` |
| Shell safety | Blocklist dangerous commands | Block rm/dd/mkfs/chmod 777/shutdown |
| Project env | Docker dev containers | Consistent across all OS |
| Context freshness | Auto-refresh CLAUDE.md if >7 days | Keep project understanding current |

---

## 2. CLI Communication

### 2.1 CLI Capability Matrix

| Feature | Claude Code | Codex | Gemini CLI | Qwen CLI |
|---------|-------------|-------|------------|----------|
| Non-interactive | `-p` / `--print` | `exec` subcommand | `-p` / `--prompt` | `-p` (headless) |
| Auto-approve | `--dangerously-skip-permissions` | `--full-auto` | `--yolo` / `-y` | `--yolo` / `-y` |
| Stream JSON | `--output-format stream-json` | `--json` (NDJSON) | `--output-format stream-json` | `--output-format stream-json` |
| Plain text | `--output-format text` | default (stderr=progress, stdout=final) | default with `-p` | default with `-p` |
| JSON blob | `--output-format json` | *(use --json)* | `--output-format json` | `--output-format json` |
| Session resume | `--resume <id>` | `exec resume --last` | `--resume <id>` | `--resume <id>` |
| Max turns | `--max-turns N` | *(not documented)* | *(not documented)* | *(not documented)* |
| Context file | `CLAUDE.md` (auto) | `AGENTS.md` (auto) | `GEMINI.md` (auto) | project files |
| Install | `npm i -g @anthropic-ai/claude-code` | `npm i -g @openai/codex` | `npm i -g @google/gemini-cli` | `npm i -g @qwen-code/qwen-code` |

### 2.2 Full Commands

```bash
# Claude Code — coder role
claude -p "task" --dangerously-skip-permissions --output-format stream-json

# Codex — coder role
codex exec --full-auto --json "task"

# Gemini CLI — reviewer/tester role
gemini -p "task" --yolo --output-format stream-json

# Qwen CLI — reviewer role
qwen -p "task" --yolo --output-format stream-json
```

### 2.3 Stream-JSON Parser

All CLIs emit NDJSON. DevBot uses a unified parser:

```python
async def read_cli_stream(process, reporter):
    """Universal stream-json reader for all CLIs."""
    async for raw_line in process.stdout:
        line = raw_line.decode("utf-8").strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            await reporter.on_text(line)  # plain text fallback
            continue

        etype = event.get("type", "")
        if etype == "assistant":
            content = event.get("message", {}).get("content", [])
            for block in content:
                if block.get("type") == "text":
                    await reporter.on_text(block["text"])
        elif etype == "tool_use":
            await reporter.on_tool_use(event.get("name"), event.get("input", {}))
        elif etype == "result":
            await reporter.on_complete(
                success=(event.get("subtype") == "success"),
                result=event.get("result", ""),
                duration_ms=event.get("duration_ms", 0),
            )
```

### 2.4 Adapter Configuration

```yaml
cli:
  claude_code:
    command: "claude"
    base_args: ["-p", "--output-format", "stream-json"]
    autonomy_args: ["--dangerously-skip-permissions"]
    extra_args: []
    timeout: 600
    enabled: true
    roles: ["coder"]

  codex:
    command: "codex"
    base_args: ["exec", "--json"]
    autonomy_args: ["--full-auto"]
    extra_args: []
    timeout: 600
    enabled: true
    roles: ["coder"]

  gemini_cli:
    command: "gemini"
    base_args: ["-p", "--output-format", "stream-json"]
    autonomy_args: ["--yolo"]
    extra_args: []
    timeout: 600
    enabled: true
    roles: ["reviewer", "tester"]

  qwen_cli:
    command: "qwen"
    base_args: ["-p", "--output-format", "stream-json"]
    autonomy_args: ["--yolo"]
    extra_args: []
    timeout: 600
    enabled: true
    roles: ["reviewer"]
```

Command assembly: `[command] + base_args + autonomy_args + extra_args + [task_message]`

---

## 3. Shell Execution

### 3.1 Platform Detection

| OS | Default Shell | Fallback | WSL |
|----|---------------|----------|-----|
| Windows | WSL bash | PowerShell → cmd | Auto via `shutil.which("wsl")` |
| macOS | zsh | bash | N/A |
| Linux | bash | zsh | N/A |

Override: `"run in powershell: ..."`, `"run in bash: ..."`, `"run in wsl: ..."`

WSL path auto-conversion: `C:\Users\me\project` → `/mnt/c/Users/me/project`

### 3.2 Command Safety Blocklist

DevBot refuses to execute commands matching these patterns. The router LLM is also instructed to never generate them.

```python
BLOCKED_COMMANDS = [
    # File/directory deletion
    r"\brm\b",             # rm, rm -rf, rm -r
    r"\brmdir\b",
    r"\bunlink\b",
    r"\bshred\b",

    # Disk formatting / raw writes
    r"\bmkfs\b",           # mkfs, mkfs.ext4, etc.
    r"\bdd\b",             # dd if=/dev/zero ...
    r"\bfdisk\b",
    r"\bparted\b",
    r"\bformat\b",         # Windows format

    # Dangerous permission changes
    r"chmod\s+777",        # chmod 777
    r"chmod\s+-R",         # recursive chmod
    r"chown\s+-R",         # recursive chown

    # System shutdown/reboot
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bhalt\b",
    r"\bpoweroff\b",
    r"\binit\s+0\b",
    r"\binit\s+6\b",

    # Fork bombs / dangerous redirects
    r":\(\)\{",            # :(){ :|:& };:
    r">\s*/dev/sd",        # writing to raw devices
    r">\s*/dev/null.*2>&1.*&",  # background + suppress all output (suspicious)
]

def is_command_blocked(command: str) -> tuple[bool, str | None]:
    """Check if a command matches the blocklist. Returns (blocked, reason)."""
    for pattern in BLOCKED_COMMANDS:
        if re.search(pattern, command, re.IGNORECASE):
            return True, f"Blocked pattern: {pattern}"
    return False, None
```

When a blocked command is detected:

```
You: "clean up old logs with rm -rf /var/log/old/*"
DevBot: 🚫 **Command blocked** — `rm` is on the safety blocklist.
        This protects against accidental destructive operations.
        If you really need this, run it manually in your terminal.
```

### 3.3 OpenClaw Management

OpenClaw runs in WSL. DevBot manages it via shell commands:

```yaml
# In config — registered as a "service" that DevBot knows about
services:
  openclaw:
    shell: "wsl"
    commands:
      start: "cd ~/openclaw && npm start"
      stop: "cd ~/openclaw && npm stop"
      restart: "cd ~/openclaw && npm restart"
      status: "cd ~/openclaw && npm run status"
      logs: "cd ~/openclaw && tail -50 logs/openclaw.log"
```

```
You: "restart openclaw"
LLM: → run_shell(command="cd ~/openclaw && npm restart", shell="wsl")
DevBot: 🔧 Running in WSL: cd ~/openclaw && npm restart
DevBot: ✅ OpenClaw restarted
```

---

## 4. Review Pipeline

### 4.1 Overview

The review pipeline is a fully automatic multi-agent workflow with harness engineering integration:

```
┌──────────────────────────────────────────────────────────────┐
│                    REVIEW PIPELINE                             │
│                                                                │
│  0. PLAN       (complex tasks) generate execution plan         │
│       │        check into docs/plans/, coder follows it        │
│                                                                │
│  1. BRANCH     git checkout -b feature/<llm-generated-name>   │
│       │                                                        │
│  2. CODE       coder CLI (claude/codex) implements task        │
│       │        reads AGENTS.md → follows pointers to docs/     │
│                                                                │
│  3. LINT       run project linters + structural tests          │
│       │        if violations → feed errors to coder, loop      │
│                                                                │
│  4. COMMIT     git add -A && git commit -m "<message>"         │
│       │                                                        │
│  5. REVIEW     reviewer CLI(s) review git diff against main    │
│       │        output: APPROVED or CHANGES_REQUESTED           │
│                                                                │
│  6. DECISION   parse structured verdict                        │
│       ├── APPROVED → go to step 7                              │
│       └── CHANGES_REQUESTED → feed back to coder (step 2)     │
│           └── max 10 cycles, then stop                         │
│                                                                │
│  7. TEST       shell runs test command (npm test / pytest)     │
│       │        reviewer CLI interprets any failures            │
│       ├── PASS → go to step 8                                  │
│       └── FAIL → feed failures to coder (step 2), loop        │
│                                                                │
│  8. PUSH       git push origin feature/<name>                  │
│       │                                                        │
│  9. PR         gh pr create --title "..." --body "..."         │
│                LLM auto-generates title + description          │
└─────────────────────────────────────────────────
...[truncated]