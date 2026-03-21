"""Dangerous command blocklist — patterns that DevBot refuses to execute."""

from __future__ import annotations

import re

# Patterns that are always blocked, regardless of context.
# Each entry is a regex pattern matched against the full command string.
BLOCKED_PATTERNS: list[tuple[str, str]] = [
    # File/directory deletion
    (r"\brm\b", "rm (file deletion)"),
    (r"\brmdir\b", "rmdir (directory deletion)"),
    (r"\bunlink\b", "unlink (file deletion)"),
    (r"\bshred\b", "shred (secure file deletion)"),

    # Disk formatting / raw writes
    (r"\bmkfs\b", "mkfs (disk formatting)"),
    (r"\bdd\b", "dd (raw disk write)"),
    (r"\bfdisk\b", "fdisk (partition editor)"),
    (r"\bparted\b", "parted (partition editor)"),
    (r"\bformat\b", "format (Windows disk format)"),

    # Dangerous permission changes
    (r"chmod\s+777", "chmod 777 (world-writable permissions)"),
    (r"chmod\s+-R", "chmod -R (recursive permission change)"),
    (r"chown\s+-R", "chown -R (recursive ownership change)"),

    # System shutdown/reboot
    (r"\bshutdown\b", "shutdown"),
    (r"\breboot\b", "reboot"),
    (r"\bhalt\b", "halt"),
    (r"\bpoweroff\b", "poweroff"),
    (r"\binit\s+0\b", "init 0 (halt)"),
    (r"\binit\s+6\b", "init 6 (reboot)"),

    # Fork bombs / dangerous redirects
    (r":\(\)\s*\{", "fork bomb"),
    (r">\s*/dev/sd", "raw device write"),
]

_COMPILED = [(re.compile(pat, re.IGNORECASE), reason) for pat, reason in BLOCKED_PATTERNS]


def is_command_blocked(command: str) -> tuple[bool, str | None]:
    """Check if a command matches the blocklist.

    Returns (blocked, reason) where reason is a human-readable explanation
    or None if the command is allowed.
    """
    for compiled, reason in _COMPILED:
        if compiled.search(command):
            return True, reason
    return False, None
