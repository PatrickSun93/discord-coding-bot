"""Adaptive Discord streamer: real-time (<30s) then batched (>30s)."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    pass


class DiscordStreamer:
    """Streams CLI output to a Discord channel with adaptive batching.

    - First batch_threshold seconds: edits a single message with the last 15 lines
    - After batch_threshold seconds: posts batch summaries every batch_interval seconds
    - On finish: sends a rich embed
    """

    def __init__(
        self,
        channel: discord.abc.Messageable,
        batch_threshold: int = 30,
        batch_interval: int = 15,
        max_lines: int = 200,
    ):
        self.channel = channel
        self.batch_threshold = batch_threshold
        self.batch_interval = batch_interval
        self.max_lines = max_lines

        self.start_time = time.monotonic()
        self.last_flush = time.monotonic()
        self.buffer: list[str] = []
        self.all_output: list[str] = []
        self.progress_msg: discord.Message | None = None

    async def on_output(self, line: str) -> None:
        self.all_output.append(line)
        elapsed = time.monotonic() - self.start_time

        if elapsed < self.batch_threshold:
            await self._stream_realtime()
        else:
            self.buffer.append(line)
            if time.monotonic() - self.last_flush > self.batch_interval:
                await self._flush_batch()

    async def _stream_realtime(self) -> None:
        recent = self.all_output[-15:]
        text = "\n".join(recent)
        # Discord code block max ~1900 chars to stay under 2000 total
        if len(text) > 1800:
            text = "..." + text[-1797:]
        content = f"⚡ **Running...**\n```\n{text}\n```"
        try:
            if self.progress_msg:
                await self.progress_msg.edit(content=content)
            else:
                self.progress_msg = await self.channel.send(content)
        except discord.HTTPException:
            pass

    async def _flush_batch(self) -> None:
        if not self.buffer:
            return
        lines = self.buffer[-20:]
        text = "\n".join(lines)
        if len(text) > 1800:
            text = "..." + text[-1797:]
        content = (
            f"📦 **Progress** ({len(self.all_output)} lines total):\n"
            f"```\n{text}\n```"
        )
        try:
            await self.channel.send(content)
        except discord.HTTPException:
            pass
        self.buffer.clear()
        self.last_flush = time.monotonic()

    async def send_result(
        self,
        returncode: int,
        cli_name: str,
        project: str,
        task: str,
        duration: float,
    ) -> None:
        """Send the final result as a rich Discord embed."""
        # Flush any remaining batch output first
        await self._flush_batch()

        success = returncode == 0
        embed = discord.Embed(
            title="✅ Task Complete" if success else "❌ Task Failed",
            color=discord.Color.green() if success else discord.Color.red(),
        )
        embed.add_field(name="CLI", value=cli_name, inline=True)
        embed.add_field(name="Project", value=project, inline=True)
        embed.add_field(name="Duration", value=f"{duration:.0f}s", inline=True)
        embed.add_field(name="Exit Code", value=str(returncode), inline=True)
        embed.add_field(name="Task", value=task[:200], inline=False)

        summary_lines = self.all_output[-20:]
        summary = "\n".join(summary_lines)
        if len(summary) > 900:
            summary = "..." + summary[-897:]
        if summary:
            embed.add_field(
                name="Output (last 20 lines)",
                value=f"```\n{summary}\n```",
                inline=False,
            )

        try:
            await self.channel.send(embed=embed)
        except discord.HTTPException:
            pass
