"""SQLite task history — records every completed task execution."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

import platformdirs


def _db_path() -> Path:
    data_dir = Path(platformdirs.user_data_dir("devbot"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / "history.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS task_history (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            ts        REAL    NOT NULL,
            cli_name  TEXT    NOT NULL,
            project   TEXT    NOT NULL,
            task      TEXT    NOT NULL,
            returncode INTEGER NOT NULL,
            duration  REAL    NOT NULL
        )
    """)
    conn.commit()
    return conn


@dataclass
class TaskRecord:
    id: int
    ts: float
    cli_name: str
    project: str
    task: str
    returncode: int
    duration: float

    @property
    def success(self) -> bool:
        return self.returncode == 0


def record_task(
    cli_name: str,
    project: str,
    task: str,
    returncode: int,
    duration: float,
) -> None:
    """Insert a completed task record into the history database."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO task_history (ts, cli_name, project, task, returncode, duration) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), cli_name, project, task, returncode, duration),
        )


def get_recent(limit: int = 10) -> list[TaskRecord]:
    """Return the most recent task records, newest first."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM task_history ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return [TaskRecord(**dict(row)) for row in rows]
