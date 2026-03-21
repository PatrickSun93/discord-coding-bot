Now I understand the problem. Let me read the runner and commands files for the full picture.
Now I have a complete picture of the problem. The root cause is clear:

1. `TaskManager` has a single `_current` slot — one task globally
2. `on_message()` blocks ALL new messages if `is_busy()` returns True (regardless of project)
3. `execute()` raises `RuntimeError` if anything is running at all

The fix: change `TaskManager` to a per-project dict, move the busy gate to per-project, and update the slash commands.
Now update `client.py` — remove the global busy gate in `on_message`, add per-project checks in `_run_cli` and `_analyze_project`:
Now add the per-project busy check in `_run_cli`, right after project resolution:
Now add the same per-project check in `_analyze_project`, after project resolution:
Now update `formatter.py` to handle multiple tasks:
Now update `commands.py` — fix the `/status` call and add optional project param to `/cancel`:
Now run the smoke test to verify nothing is broken:
All checks pass. Let me also quickly verify the executor shell module (which had a modified file per git status):
All good. Here's a summary of what was changed and why:

---

**Root cause:** `TaskManager` held a single `_current` slot and `on_message()` blocked all new requests whenever anything was running — no concept of per-project isolation.

**Changes made:**

**`executor/manager.py`** — Core fix:
- Replaced `_current: TaskInfo | None` → `_tasks: dict[str, TaskInfo]` (keyed by project name)
- Replaced `_process` → `_processes: dict[str, Process]`
- `is_busy(project=None)` — checks a specific project, or any if `None`
- `all_tasks()` — returns snapshot of all running tasks
- `execute()` — raises only if *that project* is already busy; different projects run concurrently
- `cancel(project=None)` — cancels specific project or all

**`bot/client.py`** — Remove global gate, add per-project gate:
- Removed `if self.task_manager.is_busy(): return` from `on_message()` — messages are no longer blocked globally
- Added per-project `is_busy(project_name)` check in `_run_cli()` and `_analyze_project()` after the project is resolved

**`bot/formatter.py`** — Updated `format_status()` to accept the full tasks dict and display all running tasks

**`bot/commands.py`** — Updated `/status` to show all tasks; `/cancel` now accepts an optional `project` parameter to cancel a specific project or all
All good. Here's a summary of what was changed and why:

---

**Root cause:** `TaskManager` held a single `_current` slot and `on_message()` blocked all new requests whenever anything was running — no concept of per-project isolation.

**Changes made:**

**`executor/manager.py`** — Core fix:
- Replaced `_current: TaskInfo | None` → `_tasks: dict[str, TaskInfo]` (keyed by project name)
- Replaced `_process` → `_processes: dict[str, Process]`
- `is_busy(project=None)` — checks a specific project, or any if `None`
- `all_tasks()` — returns snapshot of all running tasks
- `execute()` — raises only if *that project* is already busy; different projects run concurrently
- `cancel(project=None)` — cancels specific project or all

**`bot/client.py`** — Remove global gate, add per-project gate:
- Removed `if self.task_manager.is_busy(): return` from `on_message()` — messages are no longer blocked globally
- Added per-project `is_busy(project_name)` check in `_run_cli()` and `_analyze_project()` after the project is resolved

**`bot/formatter.py`** — Updated `format_status()` to accept the full tasks dict and display all running tasks

**`bot/commands.py`** — Updated `/status` to show all tasks; `/cancel` now accepts an optional `project` parameter to cancel a specific project or all