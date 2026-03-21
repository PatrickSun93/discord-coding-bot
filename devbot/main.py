"""DevBot entry point."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from devbot.config.settings import load_config
from devbot.bot.client import DevBotClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Suppress discord.py voice warnings — we don't use voice features.
class _NoVoiceWarning(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "voice will NOT be supported" not in record.getMessage()

logging.getLogger("discord.client").addFilter(_NoVoiceWarning())


async def _run(config) -> None:
    client = DevBotClient(config)

    # Register SIGTERM handler on platforms that support it (Unix only).
    # SIGINT (Ctrl+C) is handled by discord.py itself on all platforms.
    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(
                sig,
                lambda: asyncio.ensure_future(client.close()),
            )

    try:
        logger.info("Starting DevBot...")
        await client.start(config.discord.token)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        if not client.is_closed():
            await client.close()
        logger.info("DevBot shut down cleanly.")


def main() -> None:
    try:
        config = load_config()
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    if not config.discord.token:
        logger.error("Discord token is empty. Set DISCORD_BOT_TOKEN or update your config.")
        sys.exit(1)

    if not config.discord.owner_id:
        logger.error("owner_id is not set. Set DISCORD_OWNER_ID or update your config.")
        sys.exit(1)

    try:
        asyncio.run(_run(config))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
