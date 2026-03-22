# CLAUDE.md

This file gives repo-specific guidance to Claude Code when working in this project.

## Environment

Conda environment: `devbot` (Python 3.11)

```bash
conda activate devbot

# Install / reinstall after dependency changes
pip install -e .

# Start the bot
devbot start

# Check local machine health
devbot doctor

# Focused tests
python test_todo.py
python test_auto_restart.py
python -m unittest -v test_healthcheck.py
python -m unittest -v test_user_scenarios.py
python -m unittest -v test_pipeline_workflow.py

# Smoke tests
python smoke_test.py
python test_runner.py
python test_full_pipeline.py
python test_router_import.py
```

On this Windows machine the config path is:
`C:\Users\peido\AppData\Local\devbot\devbot\config.yaml`

## Current State

Architecture document: `devbot-architecture-v4-final.md`

Implemented and active:
- Discord bot with owner auth and channel restriction support
- MiniMax primary router with Ollama fallback
- Claude Code, Codex, Gemini CLI, and Qwen CLI adapters
- Project profiles, role registry, workflow registry, and persisted run artifacts
- Full `feature_delivery` pipeline with branch/create-review-QA-release orchestration
- Durable workflow step logs in `timeline.md` and `events.jsonl`
- `/status` surfaces active pipeline log paths while a pipeline is still running
- Todo queue from `todos.md` with `!todo add/list/run/status/cancel`
- Router tools for `run_pipeline` and `todo_add`
- Auto-restart after successful code changes when project restart config is present
- Manual restart via `!project restart <name>` and `/project restart <name>`
- Startup machine healthcheck for configured CLIs and LLM backends
- Shared health reporting in `devbot doctor` and `/doctor`

Not fully implemented yet:
- Busy-CLI interactive handling such as assign / hold / skip
- End-to-end Discord integration tests against the live API

## High-Level Flow

```text
Discord message
  -> DevBotClient.on_message()
  -> LLMRouter.route() unless intercepted by !todo / !project
  -> tool dispatch
     -> run_cli        -> TaskManager -> CLI adapter -> subprocess stream
     -> run_pipeline   -> FeatureDeliveryPipeline -> branch/code/review/qa/release
     -> run_shell      -> shell blocklist -> shell executor
     -> read_context   -> project context loader
     -> read_files     -> bounded file bundle
     -> analyze_project -> reviewer-style prompt -> CLI run artifacts
  -> Discord replies + reactions
```

Startup path:

```text
devbot start
  -> load_config()
  -> run_machine_healthcheck()
  -> log result
  -> start Discord client
  -> on_ready() optionally posts startup healthcheck to configured channel
```

## Important Runtime Rules

- Owner-only bot: only `config.discord.owner_id` is allowed to drive the bot.
- Ad-hoc CLI work is gated by project and CLI:
  - one running task per project
  - one running task per CLI across projects
- Feature pipelines hold a project-level lock across all internal stages and honor `/cancel`.
- Todo queue is parallel by CLI, but still prevents two active items on the same project.
- Manual project restart only accepts a registered project name, not an arbitrary path.
- Auto-restart is opt-in per project via `auto_restart: true` plus either:
  - `projects.<name>.commands.restart`
  - `projects.<name>.restart_service`
- Manual and auto-restart attempts also persist run artifacts under `.devbot/runs/restart/`
- Never use `shell=True`; subprocesses must stay argument-based.
- `cli.py` output must remain ASCII-friendly for Windows terminals.
- CLI adapters should keep the command shape:
  - `[command] + base_args + autonomy_args + extra_args + [task]`
- On Windows, prompt-based `.CMD` wrappers need prompt normalization; keep that behavior intact.
- On Windows with WSL, `run_shell()` must keep a Windows host `cwd` for `wsl.exe` and do the Linux-side `cd /mnt/...` inside the command.
- Codex defaults should include `--skip-git-repo-check` so temp repos and scaffolded repos can run without manual trust setup.

## Main Modules

```text
devbot/
├── bot/
│   ├── client.py            # message handling, !todo, !project restart, startup health post
│   ├── commands.py          # slash commands including /project restart and /doctor
│   └── formatter.py         # status, project list, todo formatting
├── config/
│   ├── settings.py          # typed config loader
│   └── default_config.yaml  # default template
├── context/
│   ├── project.py           # resolve project names and paths
│   ├── loader.py            # project context loading
│   └── files.py             # bounded file selection
├── executor/
│   ├── manager.py           # running-task registry and CLI/project busy checks
│   ├── auto_restart.py      # change detection and restart plan resolution
│   ├── runner.py            # subprocess execution
│   ├── stream.py            # Discord streaming
│   ├── stream_parser.py     # NDJSON/plain-text normalization
│   ├── adapters/            # Claude/Codex/Gemini/Qwen adapters
│   └── shell/               # blocklist, platform detection, shell execution
├── healthcheck.py           # startup and doctor machine/provider healthchecks
├── llm/
│   ├── router.py            # MiniMax primary, Ollama fallback
│   └── tools_schema.py      # router tool definitions and system prompt
├── todo/
│   ├── parser.py            # todos.md read/write
│   ├── validator.py         # CLI/project normalization and validation
│   ├── executor.py          # queue dispatch and result archiving
│   ├── archiver.py          # done.md output
│   └── models.py            # todo dataclasses
├── workflow/
│   ├── pipeline.py          # feature-delivery pipeline executor
│   ├── registry.py          # roles + workflows
│   ├── prompts.py           # prompt builders
│   └── store.py             # run artifacts + events under .devbot/runs/
├── cli.py                   # devbot init / doctor / start
├── history.py               # sqlite task history
└── main.py                  # startup entry point
```

## Router and Tools

The router currently exposes 9 tools:

- `run_cli`
- `run_pipeline`
- `run_shell`
- `read_context`
- `read_files`
- `analyze_project`
- `todo_add`
- `ask_clarification`
- `list_projects`

MiniMax is the primary routing backend. Ollama is the fallback backend. The shared machine healthcheck verifies both using the configured models.

## Todo Queue

Todo items live in `~/.devbot/todos.md` by default.

Supported commands:
- `!todo add <cli> <project> <task>`
- `!todo add <cli> <project> <task> --priority 1`
- `!todo list`
- `!todo run`
- `!todo status`
- `!todo cancel`

Behavior:
- validates CLI name, project, and local binary availability before queue start
- runs all tasks in priority order
- allows parallel work across distinct CLIs
- prevents concurrent work on the same project
- executes `pipeline` todo items through the real feature pipeline, not a coder-only shortcut
- archives completed items to `done.md`
- converts unexpected runner exceptions into failed archived todo results

## Pipeline Behavior

`feature_delivery` now runs:
- branch creation
- optional planning
- coder stage
- optional lint stage
- commit
- reviewer CLI stage
- QA/test stage
- release/push/PR assessment

Each run persists:
- `run.json`
- `timeline.md`
- `events.jsonl`
- stage prompts and outputs
- diff / QA / release artifacts

## Restart Behavior

Manual restart:
- `!project restart <name>`
- `/project restart <name>`

Auto-restart:
- runs only after successful code tasks
- compares project snapshots before and after execution
- ignores doc-only changes such as `README.md`
- surfaces restart failure back to Discord and marks todo work failed if the restart step fails

## Healthcheck Behavior

Shared implementation: `devbot/healthcheck.py`

What it checks:
- configured CLI commands on `PATH`
- live CLI prompt probes, so auth/config failures show up as unhealthy instead of “installed”
- MiniMax primary model availability with a small live probe
- fallback OpenAI-compatible backend availability and configured model presence

Where it runs:
- automatically during `devbot start`
- manually through `devbot doctor`
- manually through `/doctor`

Startup reporting:
- logged in the terminal every start
- posted once to the configured Discord channel if `discord.channel_id` is set

## Slash Commands

Current slash surface:
- `/status`
- `/cancel`
- `/projects`
- `/project add <name> <path>`
- `/project restart <name>`
- `/config reload`
- `/history`
- `/shells`
- `/doctor`
- `/roles`
- `/workflows`

## Test Guidance

Use these tests when touching the related subsystems:

- Startup and provider healthchecks:
  - `python -m unittest -v test_healthcheck.py`
- Todo queue, restart, and slash command scenarios:
  - `python -m unittest -v test_user_scenarios.py`
- Pipeline orchestration and durable workflow logs:
  - `python -m unittest -v test_pipeline_workflow.py`
- Todo queue focused coverage:
  - `python test_todo.py`
- Restart focused coverage:
  - `python test_auto_restart.py`
- Broad local regression:
  - `python smoke_test.py`
  - `python test_runner.py`
  - `python -m unittest -v test_shell_executor.py`
  - `python test_full_pipeline.py`
  - `python test_router_import.py`

Do not rely on `test_minimax.py` for normal local regression; it is a live network check.
Do not rely on `test_projects.py` unless the local machine-specific project registry is expected to match.

## Dependencies

```text
discord.py>=2.3
anthropic>=0.40
openai>=1.0
httpx>=0.27
pyyaml>=6.0
platformdirs>=4.0
python-dotenv>=1.0
```
