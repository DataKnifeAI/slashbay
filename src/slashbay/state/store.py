from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from slashbay.state.models import Run, RunStatus


class Store(Protocol):
    def put(self, run: Run) -> Run: ...
    def get(self, run_id: str) -> Run | None: ...
    def list_active(self) -> list[Run]: ...
    def count_active(self) -> int: ...


_ACTIVE = {
    RunStatus.received,
    RunStatus.triaged,
    RunStatus.berthing,
    RunStatus.running,
}


class MemoryStore:
    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}

    def put(self, run: Run) -> Run:
        run.touch()
        self._runs[run.id] = run
        return run

    def get(self, run_id: str) -> Run | None:
        return self._runs.get(run_id)

    def list_active(self) -> list[Run]:
        return [run for run in self._runs.values() if run.status in _ACTIVE]

    def count_active(self) -> int:
        return len(self.list_active())


class SqliteStore:
    def __init__(self, path: str) -> None:
        self._path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def put(self, run: Run) -> Run:
        run.touch()
        payload = run.model_dump_json()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (id, payload, status, created_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload,
                    status = excluded.status
                """,
                (run.id, payload, run.status.value, run.created_at.isoformat()),
            )
            conn.commit()
        return run

    def get(self, run_id: str) -> Run | None:
        with self._connect() as conn:
            row = conn.execute("SELECT payload FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return Run.model_validate(json.loads(row["payload"]))

    def list_active(self) -> list[Run]:
        placeholders = ",".join("?" for _ in _ACTIVE)
        statuses = [s.value for s in _ACTIVE]
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT payload FROM runs WHERE status IN ({placeholders})",
                statuses,
            ).fetchall()
        return [Run.model_validate(json.loads(row["payload"])) for row in rows]

    def count_active(self) -> int:
        return len(self.list_active())


def build_store(dsn: str) -> Store:
    if dsn in {"memory://", "memory", ""}:
        return MemoryStore()
    parsed = urlparse(dsn)
    if parsed.scheme == "sqlite":
        path = parsed.path
        if dsn.startswith("sqlite:///"):
            path = dsn.removeprefix("sqlite:///")
        if path == ":memory:":
            return MemoryStore()
        return SqliteStore(path)
    raise ValueError(f"unsupported state DSN: {dsn}")
