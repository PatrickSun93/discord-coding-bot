"""Healthcheck tests for machine startup and doctor reporting.

Run with:
  conda run -n devbot python -m unittest -v test_healthcheck.py
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from devbot.bot.client import DevBotClient
from devbot.healthcheck import (
    HealthCheckItem,
    HealthReport,
    format_health_report,
    run_machine_healthcheck,
)
from test_support import FakeChannel, build_config


class HealthcheckTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    async def asyncTearDown(self) -> None:
        self.temp_dir.cleanup()

    async def test_run_machine_healthcheck_reports_success(self) -> None:
        config = build_config(self.root)
        config.llm.primary.api_key = "test-key"

        def fake_which(command: str) -> str | None:
            if command in {"cmd", "sh", "claude", "codex", "gemini", "qwen"}:
                return f"C:/tools/{command}.exe"
            return None

        with (
            patch("devbot.healthcheck.shutil.which", side_effect=fake_which),
            patch(
                "devbot.healthcheck._probe_cli_health",
                new=AsyncMock(
                    side_effect=lambda _config, *, cli_key, label, resolved_path: HealthCheckItem(
                        name=label,
                        status="ok",
                        detail=f"`{cli_key}` ready at `{resolved_path}`",
                        critical=True,
                    )
                ),
            ),
            patch("devbot.healthcheck._probe_minimax_model", return_value="OK"),
            patch(
                "devbot.healthcheck._list_openai_models",
                new=AsyncMock(return_value=[config.llm.fallback.model, "other-model"]),
            ),
        ):
            report = await run_machine_healthcheck(config)

        self.assertFalse(report.has_failures())
        self.assertEqual(len(report.items), 6)
        self.assertIn("6 ok", report.summary_line())
        rendered = format_health_report(report, markdown=False)
        self.assertIn("MiniMax", rendered)
        self.assertIn("Claude Code", rendered)

    async def test_run_machine_healthcheck_reports_missing_cli_and_provider_failures(self) -> None:
        config = build_config(
            self.root / "broken",
            cli_commands={"codex": "missing-codex"},
        )
        config.llm.primary.api_key = "test-key"

        def fake_which(command: str) -> str | None:
            if command == "missing-codex":
                return None
            if command == "cmd":
                return "C:/Windows/System32/cmd.exe"
            return None

        with (
            patch("devbot.healthcheck.shutil.which", side_effect=fake_which),
            patch(
                "devbot.healthcheck._probe_cli_health",
                new=AsyncMock(
                    side_effect=lambda _config, *, cli_key, label, resolved_path: HealthCheckItem(
                        name=label,
                        status="fail" if cli_key == "claude_code" else "ok",
                        detail=(
                            "probe rejected credentials"
                            if cli_key == "claude_code"
                            else f"`{cli_key}` ready at `{resolved_path}`"
                        ),
                        critical=True,
                    )
                ),
            ),
            patch("devbot.healthcheck._probe_minimax_model", side_effect=RuntimeError("401 unauthorized")),
            patch(
                "devbot.healthcheck._list_openai_models",
                new=AsyncMock(return_value=["not-the-configured-model"]),
            ),
        ):
            report = await run_machine_healthcheck(config)

        self.assertTrue(report.has_failures())
        items = {item.name: item for item in report.items}
        self.assertEqual(items["Codex"].status, "fail")
        self.assertIn("missing-codex", items["Codex"].detail)
        self.assertEqual(items["Claude Code"].status, "fail")
        self.assertIn("probe rejected credentials", items["Claude Code"].detail)
        self.assertEqual(items["Primary LLM"].status, "fail")
        self.assertIn("MiniMax", items["Primary LLM"].detail)
        self.assertEqual(items["Fallback LLM"].status, "fail")
        self.assertIn("reachable, but model", items["Fallback LLM"].detail)

    async def test_client_announces_startup_health_once(self) -> None:
        config = build_config(self.root / "client")
        config.discord.channel_id = 123
        client = DevBotClient(config)
        try:
            channel = FakeChannel()
            client.get_channel = lambda _channel_id: channel  # type: ignore[method-assign]
            client._startup_health_report = HealthReport(
                items=[
                    HealthCheckItem(name="Claude Code", status="ok", detail="available"),
                    HealthCheckItem(name="Primary LLM", status="fail", detail="MiniMax unavailable"),
                ]
            )

            await client._announce_startup_health()
            await client._announce_startup_health()
        finally:
            await client.close()

        self.assertEqual(len(channel.messages), 1)
        self.assertIn("Startup Healthcheck", channel.messages[0])
        self.assertIn("MiniMax unavailable", channel.messages[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
