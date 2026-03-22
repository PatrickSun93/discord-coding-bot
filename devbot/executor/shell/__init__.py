"""Shell execution package."""

from devbot.executor.shell.blocklist import is_command_blocked
from devbot.executor.shell.executor import ShellResult, run_shell
from devbot.executor.shell.platform import PlatformInfo, detect_platform, resolve_shell

__all__ = [
    "is_command_blocked",
    "run_shell",
    "ShellResult",
    "detect_platform",
    "resolve_shell",
    "PlatformInfo",
]
