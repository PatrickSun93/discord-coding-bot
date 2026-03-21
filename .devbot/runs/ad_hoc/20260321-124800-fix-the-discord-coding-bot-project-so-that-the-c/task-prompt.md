You are working inside DevBot's project workflow.

Project: discord-coding-bot
Type: generic
Description: Discord AI Bot (multi-CLI router) - this project
Agent context docs: CLAUDE.md, AGENTS.md, GEMINI.md
Architecture docs: ARCHITECTURE.md, *architecture*.md, docs/**/*architecture*.md, docs/**/architecture*.md
Product docs: README.md

Run directory: D:\devitems\discord-coding-bot\.devbot\runs\ad_hoc\20260321-124800-fix-the-discord-coding-bot-project-so-that-the-c

Project context:
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

DevBot is a self-hoste
...[truncated]

Task:
Fix the discord-coding-bot project so that the coding CLI can work in parallel on different projects. Currently only 1 CLI is working on one project at a time. This is the highest priority task.

Investigate the current architecture and implementation to understand:
1. How projects are currently locked/assigned to a single CLI
2. Why parallel processing isn't working across different projects
3. What needs to change to allow multiple CLIs to work on different projects simultaneously

Then implement the fix to enable true parallel processing of different projects.