"""Universal stream-JSON parser for CLI output (Claude Code, Gemini, Qwen, Codex).

All CLIs emit NDJSON when run with --output-format stream-json / --json.
This module parses each line and extracts human-readable text from the events.
Falls back to treating the line as plain text if it's not valid JSON.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

# Event types we extract text from
_TEXT_TYPES = {"text", "text_delta"}


async def parse_cli_line(
    raw_line: str,
    on_text: Callable[[str], Awaitable[None]],
) -> None:
    """Parse one NDJSON line from a CLI stream.

    Extracts displayable text from known event types and passes it to on_text.
    Silently drops non-text events (tool_use, tool_result, system, etc.).
    Falls back to passing the raw line if JSON parsing fails.
    """
    line = raw_line.strip()
    if not line:
        return

    try:
        event = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        # Plain text output — pass through as-is
        await on_text(line)
        return

    etype = event.get("type", "")

    if etype == "assistant":
        # Claude Code / Gemini stream-json format
        content = event.get("message", {}).get("content", [])
        for block in content:
            btype = block.get("type", "")
            if btype in _TEXT_TYPES:
                text = block.get("text") or block.get("delta", {}).get("text", "")
                if text:
                    await on_text(text)

    elif etype in ("text", "content_block_delta"):
        # Some CLIs emit top-level text events
        text = (
            event.get("text")
            or event.get("delta", {}).get("text", "")
        )
        if text:
            await on_text(text)

    elif etype == "result":
        # Final result event — show the result text if present
        result_text = event.get("result", "")
        if result_text:
            await on_text(result_text)
        # Log success/failure for debugging
        subtype = event.get("subtype", "")
        duration = event.get("duration_ms", 0)
        logger.debug("CLI result: subtype=%s duration_ms=%d", subtype, duration)

    elif etype == "system":
        # Ignore system events (session init etc.)
        pass

    elif etype in ("tool_use", "tool_result"):
        # Show a brief tool-use indicator
        name = event.get("name") or event.get("tool_use_id", "tool")
        await on_text(f"[tool: {name}]")

    else:
        # Unknown event type — log at debug level, don't surface to Discord
        logger.debug("Unknown CLI event type: %s — %s", etype, line[:120])


def make_json_output_handler(
    on_text: Callable[[str], Awaitable[None]],
) -> Callable[[str], Awaitable[None]]:
    """Wrap an on_text callback with the JSON parser.

    Returns an on_output callback suitable for run_subprocess() that:
    - Parses NDJSON events and extracts text
    - Falls back to plain text for non-JSON lines
    """
    async def handler(line: str) -> None:
        await parse_cli_line(line, on_text)

    return handler
