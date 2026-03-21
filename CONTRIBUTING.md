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
