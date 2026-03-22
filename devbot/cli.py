"""DevBot CLI helper commands: init, doctor, start."""

from __future__ import annotations

import asyncio
import shutil
import sys
from pathlib import Path

import platformdirs
import yaml

from devbot.healthcheck import format_health_report, run_machine_healthcheck


def _config_path() -> Path:
    return Path(platformdirs.user_config_dir("devbot")) / "config.yaml"


def cmd_init() -> None:
    """Interactive first-time setup wizard."""
    config_path = _config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if config_path.exists():
        overwrite = input(f"Config already exists at {config_path}. Overwrite? [y/N] ").strip().lower()
        if overwrite != "y":
            print("Aborted.")
            return

    print("=== DevBot Setup ===")
    token = input("Discord Bot Token: ").strip()
    owner_id = input("Your Discord User ID (owner): ").strip()
    channel_id = input("Restrict to channel ID? (leave blank for all): ").strip()
    minimax_key = input("MiniMax API Key (leave blank to skip): ").strip()

    config = {
        "discord": {
            "token": token,
            "owner_id": owner_id,
            "channel_id": channel_id or "",
        },
        "llm": {
            "primary": {
                "provider": "minimax",
                "base_url": "https://api.minimaxi.com/anthropic",
                "api_key": minimax_key,
                "model": "MiniMax-M2.7",
            },
            "fallback": {
                "provider": "ollama",
                "base_url": "http://localhost:11434/v1",
                "model": "qwen2.5:14b",
            },
        },
        "cli": {
            "claude_code": {
                "command": "claude",
                "base_args": ["-p", "--output-format", "stream-json"],
                "autonomy_args": ["--dangerously-skip-permissions"],
                "extra_args": [],
                "timeout": 600,
                "enabled": True,
                "roles": ["coder"],
            },
            "codex": {
                "command": "codex",
                "base_args": ["exec", "--json"],
                "autonomy_args": ["--full-auto"],
                "extra_args": [],
                "timeout": 600,
                "enabled": True,
                "roles": ["coder"],
            },
            "gemini_cli": {
                "command": "gemini",
                "base_args": ["-p", "--output-format", "stream-json"],
                "autonomy_args": ["--yolo"],
                "extra_args": [],
                "timeout": 600,
                "enabled": True,
                "roles": ["reviewer", "tester"],
            },
            "qwen_cli": {
                "command": "qwen",
                "base_args": ["-p", "--output-format", "stream-json"],
                "autonomy_args": ["--yolo"],
                "extra_args": [],
                "timeout": 600,
                "enabled": True,
                "roles": ["reviewer"],
            },
        },
        "shell": {
            "default": "auto",
            "timeout": 300,
            "wsl_distro": None,
        },
        "todo": {
            "file": "~/.devbot/todos.md",
            "done_file": "~/.devbot/done.md",
            "auto_start": False,
            "busy_cli_timeout": 300,
        },
        "context": {
            "max_age_days": 7,
        },
        "reporter": {
            "stream_threshold": 30,
            "batch_interval": 15,
            "max_message_length": 1900,
        },
        "projects": {},
        "team_roles": {},
        "workflows": {},
    }

    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    print(f"\nConfig written to {config_path}")
    print("Run `devbot doctor` to verify your setup, then `devbot start` to launch.")


def cmd_doctor() -> None:
    """Validate machine health, config, shells, and connectivity."""
    import platform as _platform
    print("=== DevBot Doctor ===")
    ok = True

    # Config
    config_path = _config_path()
    if config_path.exists():
        print(f"[OK] Config found: {config_path}")
        try:
            from devbot.config.settings import load_config
            cfg = load_config()
            print(f"  token set: {'yes' if cfg.discord.token else 'NO'}")
            print(f"  owner_id: {cfg.discord.owner_id or 'NOT SET'}")
        except Exception as exc:
            print(f"  [FAIL] Config load error: {exc}")
            ok = False
            cfg = None
    else:
        print(f"[FAIL] No config at {config_path} -- run `devbot init`")
        ok = False
        cfg = None

    if cfg is not None:
        report = asyncio.run(run_machine_healthcheck(cfg))
        print()
        print(format_health_report(report, markdown=False))
        ok = ok and not report.has_critical_failures()

    # Support tools
    print("\nSupport Tools:")
    for name, binary, required in [
        ("gh (GitHub CLI)", "gh",     False),
        ("docker",          "docker", False),
        ("git",             "git",    True),
    ]:
        found = shutil.which(binary)
        if found:
            print(f"  [OK] {name}: {found}")
        elif required:
            print(f"  [FAIL] {name}: not found (required)")
            ok = False
        else:
            print(f"  [--] {name}: not found (optional)")

    # Shells
    print("\nShells:")
    os_name = _platform.system()
    print(f"  OS: {os_name}")
    for shell in ("bash", "zsh", "wsl", "powershell", "pwsh", "cmd"):
        found = shutil.which(shell)
        if found:
            print(f"  [OK] {shell}: {found}")
    if os_name == "Windows" and not shutil.which("wsl"):
        print("  [--] WSL not found -- shell defaults to PowerShell")

    # Discord token validation
    try:
        from devbot.config.settings import load_config
        cfg = load_config()
        if cfg.discord.token:
            import httpx
            r = httpx.get(
                "https://discord.com/api/v10/users/@me",
                headers={"Authorization": f"Bot {cfg.discord.token}"},
                timeout=5,
            )
            if r.status_code == 200:
                data = r.json()
                print(f"[OK] Discord token valid -- bot: {data.get('username')}#{data.get('discriminator', '0')}")
            else:
                print(f"[FAIL] Discord token invalid (HTTP {r.status_code})")
                ok = False
        else:
            print("[FAIL] Discord token not set -- cannot validate")
            ok = False
    except Exception as exc:
        print(f"[--] Discord token check skipped: {exc}")

    print("\n" + ("All critical checks passed." if ok else "Fix the issues above before starting."))


def cmd_start() -> None:
    """Launch the bot."""
    from devbot.main import main
    main()


def cli_main() -> None:
    import argparse
    parser = argparse.ArgumentParser(prog="devbot", description="DevBot -- Discord AI dev assistant")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init", help="Interactive setup wizard")
    sub.add_parser("doctor", help="Validate machine health, config, and shells")
    sub.add_parser("start", help="Start the bot")

    args = parser.parse_args()
    if args.command == "init":
        cmd_init()
    elif args.command == "doctor":
        cmd_doctor()
    elif args.command == "start":
        cmd_start()
    else:
        parser.print_help()
