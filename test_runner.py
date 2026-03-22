"""Test the async subprocess runner with a real command."""

from __future__ import annotations

import asyncio
import platform
import shutil
import sys
from pathlib import Path

from devbot.executor.runner import run_subprocess


async def main():
    lines = []

    async def capture(line: str):
        lines.append(line)
        print("  >", line)

    if platform.system() == "Windows":
        cmd = ["cmd", "/c", "echo hello from devbot && echo line two"]
    else:
        cmd = ["sh", "-c", "echo hello from devbot && echo line two"]

    tmp_root = Path(".tmp-runner")
    tmp_root.mkdir(exist_ok=True)
    workdir = tmp_root / "project"
    shutil.rmtree(workdir, ignore_errors=True)
    workdir.mkdir(parents=True, exist_ok=True)

    try:
        rc = await run_subprocess(cmd, cwd=str(workdir), on_output=capture, timeout=10)
        long_lines: list[str] = []

        async def capture_long(line: str):
            long_lines.append(line)

        long_cmd = [sys.executable, "-c", "print('x' * 70000)"]
        long_rc = await run_subprocess(long_cmd, cwd=str(workdir), on_output=capture_long, timeout=10)
    except PermissionError as exc:
        print(f"runner test skipped due to sandbox permission error: {exc}")
        return
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    print(f"Exit code: {rc}")
    assert rc == 0, f"Expected 0, got {rc}"
    assert long_rc == 0, f"Expected long-line command to succeed, got {long_rc}"
    assert any("hello" in l for l in lines), f"Expected output, got: {lines}"
    assert any(len(line) >= 70000 for line in long_lines), "Expected to capture the long output line."
    print("runner test passed.")


asyncio.run(main())
