"""Cross-platform async subprocess runner."""

from __future__ import annotations

import asyncio
import platform
import subprocess
from collections.abc import Awaitable, Callable


async def run_subprocess(
    cmd: list[str],
    cwd: str,
    on_output: Callable[[str], Awaitable[None]],
    timeout: int,
    on_process: Callable[[asyncio.subprocess.Process], None] | None = None,
) -> int:
    """Run a command, stream output lines via on_output, return exit code."""
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=1024 * 1024,
        )
    except FileNotFoundError:
        await on_output(f"[error] Command not found: {cmd[0]!r} — is it installed and on PATH?")
        return 127

    if on_process is not None:
        on_process(process)

    async def read_stream(stream: asyncio.StreamReader, prefix: str = "") -> None:
        buffer = ""
        while True:
            raw = await stream.read(65536)
            if not raw:
                break
            buffer += raw.decode(errors="replace")
            while True:
                newline = buffer.find("\n")
                if newline < 0:
                    break
                line = buffer[:newline].rstrip("\r")
                buffer = buffer[newline + 1 :]
                await on_output(prefix + line)
        if buffer:
            await on_output(prefix + buffer.rstrip("\r"))

    try:
        await asyncio.wait_for(
            asyncio.gather(
                read_stream(process.stdout),
                read_stream(process.stderr, prefix="⚠ "),
            ),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        await kill_process(process)
        # Wait for OS to fully release the process (important on Windows for cwd locks)
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
        await on_output(f"[timeout] Task timed out after {timeout}s -- process killed.")
        return -1

    await process.wait()
    return process.returncode


async def kill_process(process: asyncio.subprocess.Process) -> None:
    """Cross-platform graceful termination: SIGTERM → 5s → SIGKILL / taskkill."""
    try:
        process.terminate()
    except ProcessLookupError:
        return

    try:
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        if platform.system() == "Windows":
            subprocess.run(
                ["taskkill", "/F", "/PID", str(process.pid)],
                check=False,
            )
        else:
            process.kill()
