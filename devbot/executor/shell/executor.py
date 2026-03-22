"""Async shell command executor — runs commands in bash/zsh/wsl/powershell/cmd."""

from __future__ import annotations

import asyncio
import logging
import shlex
from dataclasses import dataclass
from pathlib import Path

from devbot.executor.shell.platform import PlatformInfo, resolve_shell

logger = logging.getLogger(__name__)


@dataclass
class ShellResult:
    command: str
    shell: str
    returncode: int
    output: str   # combined stdout + stderr


async def run_shell(
    command: str,
    shell: str = "auto",
    working_dir: str | None = None,
    timeout: int = 300,
    platform_info: PlatformInfo | None = None,
) -> ShellResult:
    """Run a shell command and capture its output.

    Args:
        command: The shell command string to execute.
        shell: Shell name — "auto", "bash", "zsh", "wsl", "powershell", "cmd".
        working_dir: Working directory (cwd). None = inherit from bot process.
        timeout: Max seconds to wait before killing the process.
        platform_info: Pre-computed platform info. Auto-detected if None.

    Returns:
        ShellResult with returncode and combined output.
    """
    from devbot.executor.shell.platform import detect_platform, windows_path_to_wsl

    if platform_info is None:
        platform_info = detect_platform(shell)

    prefix, is_wsl = resolve_shell(shell, platform_info)
    resolved_shell = shell if shell != "auto" else platform_info.default_shell

    # For WSL, convert Windows working dir to WSL path
    cwd = str(Path(working_dir).resolve()) if working_dir else None
    wsl_cwd = None
    if is_wsl and cwd:
        wsl_cwd = windows_path_to_wsl(cwd)

    # Build the subprocess args
    # For shells that take -c <command_string>, we use prefix + [command]
    # For WSL, the command is passed directly as args
    if is_wsl:
        # Use bash -ic so .bashrc is sourced — npm globals, nvm, etc. are on PATH
        shell_command = command
        if wsl_cwd:
            shell_command = f"cd {shlex.quote(wsl_cwd)} && {command}"
        cmd_args = prefix + ["bash", "-ic", shell_command]
    elif resolved_shell in ("powershell", "cmd"):
        # powershell -Command <cmd> or cmd /c <cmd>
        cmd_args = prefix + [command]
    else:
        # bash/zsh: [shell, -c, command]
        cmd_args = prefix + [command]

    logger.info("shell[%s]: %s", resolved_shell, command[:120])
    logger.debug("shell cmd_args: %s", cmd_args)

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd_args,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,  # merge stderr into stdout
        )
    except FileNotFoundError as exc:
        return ShellResult(
            command=command,
            shell=resolved_shell,
            returncode=127,
            output=f"Shell not found: {exc}",
        )

    try:
        stdout_bytes, _ = await asyncio.wait_for(
            process.communicate(), timeout=timeout
        )
    except asyncio.TimeoutError:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass
        return ShellResult(
            command=command,
            shell=resolved_shell,
            returncode=-1,
            output=f"[timeout] Command timed out after {timeout}s",
        )

    output = stdout_bytes.decode(errors="replace").strip() if stdout_bytes else ""
    rc = process.returncode if process.returncode is not None else -1
    return ShellResult(command=command, shell=resolved_shell, returncode=rc, output=output)
