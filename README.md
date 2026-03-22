# DevBot

> A Discord-native AI software factory for your local projects.

Languages: **English** | [简体中文](docs/readme/README.zh-CN.md) | [Español](docs/readme/README.es.md)

DevBot turns a Discord channel into a control plane for real coding agents running on your machine. It routes natural-language requests to Claude Code, Codex, Gemini CLI, and Qwen CLI, uses MiniMax as the primary router LLM, can fall back to Ollama, and keeps durable logs for every meaningful step.

This is a self-hosted project. Your code stays in your repos, your CLIs stay on your machine, and the bot orchestrates the workflow around them.

```text
Discord
  -> DevBot
     -> Router LLM (MiniMax primary, Ollama fallback)
     -> CLI agents (Claude Code / Codex / Gemini / Qwen)
     -> Project commands, restarts, and workflow logs
```

## Why DevBot

- Discord-first workflow: drive coding, review, analysis, todo queues, and restarts from chat.
- Bring-your-own agents: use the CLI tools you already trust instead of a closed hosted runtime.
- Project-aware execution: projects carry docs, commands, pipeline defaults, reviewer preferences, and restart behavior.
- Durable observability: every important run writes structured artifacts under `.devbot/runs/`.
- Machine healthchecks: startup and `/doctor` verify CLI availability, auth state, shells, and LLM connectivity before you trust the bot.

## What It Can Do

- Route ad-hoc coding, shell, file-read, and analysis requests from Discord.
- Run a full `feature_delivery` pipeline: plan, code, review, QA, and release assessment.
- Queue deferred work with `!todo` and execute items safely across CLIs.
- Auto-restart projects after real code changes.
- Manually restart services with `!project restart <name>` or `/project restart <name>`.
- Keep step-by-step logs for ad-hoc runs, analysis runs, pipelines, todos, and restarts.
- Expose current activity with `/status`, including active pipeline run ids and log paths.

## Current Highlights

- Multi-CLI support: Claude Code, Codex, Gemini CLI, Qwen CLI
- Router backends: MiniMax primary, Ollama fallback
- Workflow system: roles, workflows, project profiles, durable run artifacts
- Todo system: add, list, run, status, cancel
- Restart system: auto-restart and manual project restart
- Shared machine healthcheck: startup, `devbot doctor`, and `/doctor`
- Repo hygiene: `ruff` configured in `pyproject.toml` and enforced in GitHub Actions

## Quick Start

### Requirements

- Python 3.11+
- Git
- A Discord bot token and your Discord user ID
- At least one supported CLI installed and available on `PATH`
  - [Claude Code](https://claude.ai/code)
  - [OpenAI Codex CLI](https://github.com/openai/codex)
  - [Gemini CLI](https://github.com/google-gemini/gemini-cli)
  - [Qwen CLI](https://github.com/QwenLM/qwen-agent)
- MiniMax API access for the primary router
- Optional: Ollama for local fallback routing

### Install

```bash
git clone https://github.com/PatrickSun93/discord-coding-bot.git
cd discord-coding-bot
conda create -n devbot python=3.11 -y
conda activate devbot
pip install -e .[dev]
```

### Initialize

```bash
devbot init
devbot doctor
devbot start
```

Config is stored in your platform config directory:

| Platform | Path |
| --- | --- |
| Windows | `%LOCALAPPDATA%\devbot\devbot\config.yaml` |
| macOS | `~/Library/Application Support/devbot/config.yaml` |
| Linux | `~/.config/devbot/config.yaml` |

If you prefer to edit config manually, start from [`devbot/config/default_config.yaml`](devbot/config/default_config.yaml).

## Example Discord Flows

```text
use codex to add rate limiting to the auth service in project backend
review the payment module in project backend with gemini for security issues
run the feature delivery pipeline for backend to add audit logging
!todo add claude_code backend refactor the retry logic --priority 1
!todo run
!project restart backend
/project restart backend
/status
/doctor
```

## Commands

### Slash Commands

| Command | Description |
| --- | --- |
| `/status` | Show running tasks, todo status, active pipeline runs, and log paths |
| `/cancel` | Cancel the current task, a project task, or all queue work |
| `/projects` | List registered projects |
| `/project add <name> <path>` | Register a project |
| `/project restart <name>` | Restart a configured project service |
| `/config reload` | Hot-reload config from disk |
| `/history` | Show recent task history |
| `/shells` | Show detected shells and current default shell |
| `/doctor` | Run the full machine healthcheck |
| `/roles` | List workflow roles and preferred CLIs |
| `/workflows` | List workflow definitions |

### Todo Commands

- `!todo add <cli> <project> <task>`
- `!todo add <cli> <project> <task> --priority 1`
- `!todo list`
- `!todo run`
- `!todo status`
- `!todo cancel`

### Project Restart Commands

- `!project restart <name>`
- `/project restart <name>`

## Project Profiles

Projects are first-class config objects, not just paths. A project can define:

- `docs` for product, architecture, and agent-context files
- `commands` for test, smoke, run, and restart actions
- `analysis` entry files and reviewer preferences
- `pipeline` coder/reviewer/tester defaults and QA settings
- `role_preferences` for planner, coder, reviewer, and release roles
- `auto_restart` or `restart_service` behavior after code changes

Example:

```yaml
projects:
  backend:
    path: "/home/user/projects/backend"
    description: "Main backend API"
    auto_restart: true
    docs:
      product: ["README.md", "docs/product/**/*.md"]
      architecture: ["ARCHITECTURE.md", "docs/architecture/**/*.md"]
      agent_context: ["CLAUDE.md", "AGENTS.md", "GEMINI.md"]
    commands:
      test: "pytest -q"
      restart: "docker compose restart backend"
      restart_shell: "bash"
    pipeline:
      coder: "codex"
      reviewers: ["qwen_cli"]
      tester: "qwen_cli"
      test_command: "pytest -q"
      max_cycles: 5
    analysis:
      entry_files: ["ARCHITECTURE.md"]
      preferred_reviewer_cli: "gemini_cli"
```

Per-project overrides can also live inside a repo-local `.devbot.yaml`.

## Durable Logs And Observability

Every important run writes a durable artifact directory under the target project:

```text
.devbot/runs/<workflow>/<run_id>/
  run.json
  timeline.md
  events.jsonl
  ...
```

This applies to:

- ad-hoc CLI runs
- analysis runs
- feature pipelines
- restart attempts

Pipeline runs also persist stage prompts, stage outputs, review reports, QA artifacts, and release summaries. The point is simple: if something went wrong, there should be a file on disk showing where and why.

## Healthcheck

DevBot performs a shared machine healthcheck at startup, in `devbot doctor`, and in `/doctor`.

It checks:

- configured CLI binaries on `PATH`
- live CLI prompt probes so auth failures are caught, not hidden
- MiniMax primary model reachability
- fallback LLM endpoint and model availability
- shell environment details

The healthcheck also classifies some CLI-specific failures more clearly. For example, Gemini eligibility or account-auth problems are surfaced as account issues rather than generic "command failed" noise.

## Architecture

```text
devbot/
├── bot/              Discord client, slash commands, message formatting
├── config/           Config loader and defaults
├── context/          Project resolution and context loading
├── executor/         Task manager, CLI adapters, shell execution, restart logic
├── llm/              Router and tool schema
├── todo/             Todo parsing, validation, queue execution, archiving
├── workflow/         Roles, workflows, prompts, durable run storage
├── healthcheck.py    Startup and doctor healthchecks
├── history.py        SQLite task history
├── cli.py            devbot init / doctor / start
└── main.py           Application entry point
```

For the detailed design and milestone plan, see [devbot-architecture-v4-final.md](devbot-architecture-v4-final.md).

## Development

### Lint

```bash
ruff check .
```

### Useful Tests

```bash
python smoke_test.py
python test_runner.py
python test_todo.py
python test_auto_restart.py
python -m unittest -v test_healthcheck.py
python -m unittest -v test_user_scenarios.py
python -m unittest -v test_pipeline_workflow.py
python -m unittest -v test_shell_executor.py
python test_full_pipeline.py
python test_router_import.py
```

`test_minimax.py` is a live network check and should be treated as an explicit integration test, not the default local regression suite.

## Multilingual Docs

- English: this `README.md` is the canonical version.
- Simplified Chinese: [`docs/readme/README.zh-CN.md`](docs/readme/README.zh-CN.md)
- Spanish: [`docs/readme/README.es.md`](docs/readme/README.es.md)

Translation updates are welcome. If behavior changes, update the English README first and then sync translations.

## Acknowledgements And Influences

This repo is its own implementation, but two external projects materially influenced how it evolved:

- [tanweai/pua](https://github.com/tanweai/pua): influenced the project's high-agency debugging style, stronger insistence on verification, and the expectation that agents should not stop at shallow guesses.
- [garrytan/gstack](https://github.com/garrytan/gstack): influenced the push toward structured roles, workflow-driven delivery, heavier review and QA stages, and treating agentic coding as an operational system rather than a single chat prompt.

Those projects did not just inspire tone. They helped shape the bar for this project's workflow design, execution discipline, and public-facing philosophy.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT. See [LICENSE](LICENSE).
