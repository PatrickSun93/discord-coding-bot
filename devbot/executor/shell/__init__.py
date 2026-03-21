"""Shell execution package."""

from devbot.executor.shell.blocklist import is_command_blocked
from devbot.executor.shell.executor import run_shell, ShellResult
from devbot.executor.shell.platform import detect_platform, resolve_shell, PlatformInfo

__all__ = [
    "is_command_blocked",
    "run_shell",
    "ShellResult",
    "detect_platform",
    "resolve_shell",
    "PlatformInfo",
]
