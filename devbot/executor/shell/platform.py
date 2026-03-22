"""Platform detection and shell resolution."""

from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass


@dataclass
class PlatformInfo:
    os_name: str          # "Windows", "Darwin", "Linux"
    default_shell: str    # resolved shell name
    available_shells: list[str]
    has_wsl: bool


def detect_platform(preferred: str = "auto", wsl_distro: str | None = None) -> PlatformInfo:
    """Detect the host OS and available shells."""
    os_name = platform.system()  # "Windows", "Darwin", "Linux"
    available: list[str] = []

    if os_name == "Windows":
        if shutil.which("wsl"):
            available.append("wsl")
        if shutil.which("powershell") or shutil.which("pwsh"):
            available.append("powershell")
        if shutil.which("cmd"):
            available.append("cmd")
        has_wsl = "wsl" in available
        if preferred == "auto":
            default = "wsl" if has_wsl else "powershell"
        else:
            default = preferred
    elif os_name == "Darwin":
        if shutil.which("zsh"):
            available.append("zsh")
        if shutil.which("bash"):
            available.append("bash")
        has_wsl = False
        if preferred == "auto":
            default = "zsh" if "zsh" in available else "bash"
        else:
            default = preferred
    else:
        # Linux
        if shutil.which("bash"):
            available.append("bash")
        if shutil.which("zsh"):
            available.append("zsh")
        has_wsl = False
        if preferred == "auto":
            default = "bash" if "bash" in available else "zsh"
        else:
            default = preferred

    return PlatformInfo(
        os_name=os_name,
        default_shell=default,
        available_shells=available,
        has_wsl=has_wsl,
    )


def resolve_shell(
    shell: str,
    platform_info: PlatformInfo,
) -> tuple[list[str], bool]:
    """Return (cmd_prefix, is_wsl) for running a command in the given shell.

    cmd_prefix is prepended before the actual command string.
    is_wsl indicates whether the command runs in WSL (path conversion may be needed).
    """
    s = shell.lower()

    if s in ("auto", ""):
        s = platform_info.default_shell

    if s == "wsl":
        prefix = ["wsl"]
        return prefix, True

    if s == "powershell":
        exe = shutil.which("pwsh") or shutil.which("powershell") or "powershell"
        return [exe, "-NoProfile", "-NonInteractive", "-Command"], False

    if s == "cmd":
        return ["cmd", "/c"], False

    if s == "bash":
        exe = shutil.which("bash") or "bash"
        return [exe, "-c"], False

    if s == "zsh":
        exe = shutil.which("zsh") or "zsh"
        return [exe, "-c"], False

    # Default fallback
    return [s, "-c"], False


def windows_path_to_wsl(path: str) -> str:
    """Convert a Windows path like C:\\Users\\x to /mnt/c/Users/x for WSL."""
    import re
    # Handle both forward and backslashes
    p = path.replace("\\", "/")
    m = re.match(r"^([A-Za-z]):/(.*)$", p)
    if m:
        drive, rest = m.groups()
        return f"/mnt/{drive.lower()}/{rest}"
    return path
