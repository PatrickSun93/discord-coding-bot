"""Shared CLI adapter factory."""

from __future__ import annotations

from devbot.executor.adapters.claude_code import ClaudeCodeAdapter
from devbot.executor.adapters.codex import CodexAdapter
from devbot.executor.adapters.gemini_cli import GeminiCLIAdapter
from devbot.executor.adapters.qwen_cli import QwenCLIAdapter


_ADAPTER_CLASSES = {
    "claude_code": ClaudeCodeAdapter,
    "codex": CodexAdapter,
    "qwen_cli": QwenCLIAdapter,
    "gemini_cli": GeminiCLIAdapter,
}


def build_adapter(cli_key: str, config):
    """Instantiate the configured adapter for the requested CLI key."""
    cli_cfg = getattr(config.cli, cli_key, None)
    if cli_cfg is None:
        raise ValueError(f"Unknown CLI: {cli_key}")

    cls = _ADAPTER_CLASSES.get(cli_key)
    if cls is None:
        raise ValueError(f"Unsupported CLI adapter: {cli_key}")

    return cls(
        command=cli_cfg.command,
        base_args=cli_cfg.base_args,
        autonomy_args=cli_cfg.autonomy_args,
        extra_args=cli_cfg.extra_args,
    )
