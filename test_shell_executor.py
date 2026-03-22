"""Shell executor integration checks."""

from __future__ import annotations

import platform
import shutil
import unittest
from pathlib import Path

from devbot.executor.shell import detect_platform, run_shell
from devbot.executor.shell.platform import windows_path_to_wsl


class ShellExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_wsl_shell_honors_windows_working_dir(self) -> None:
        if platform.system() != "Windows":
            self.skipTest("WSL cwd integration is Windows-specific.")

        platform_info = detect_platform(preferred="wsl")
        if not platform_info.has_wsl:
            self.skipTest("WSL is not available on this machine.")

        root = Path(".tmp-shell-executor")
        shutil.rmtree(root, ignore_errors=True)
        try:
            workdir = root / "project"
            workdir.mkdir(parents=True, exist_ok=True)

            result = await run_shell(
                command="pwd",
                shell="wsl",
                working_dir=str(workdir),
                timeout=30,
                platform_info=platform_info,
            )

            self.assertEqual(result.returncode, 0, result.output)
            self.assertIn(windows_path_to_wsl(str(workdir.resolve())), result.output)
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
