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
    model: "qwen2.5:14b"

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
