"""Test the async subprocess runner with a real command."""

from __future__ import annotations

import asyncio
import platform
import shutil
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
    except PermissionError as exc:
        print(f"runner test skipped due to sandbox permission error: {exc}")
        return
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    print(f"Exit code: {rc}")
    assert rc == 0, f"Expected 0, got {rc}"
    assert any("hello" in l for l in lines), f"Expected output, got: {lines}"
    print("runner test passed.")


asyncio.run(main())
