from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from slashbay.state.models import IN_FLIGHT, QUEUED_OR_IN_FLIGHT, Run, RunStatus


class Store(Protocol):
    def put(self, run: Run) -> Run: ...
    def get(self, run_id: str) -> Run | None: ...
    def list_active(self) -> list[Run]: ...
    def count_active(self) -> int: ...
    def get_by_delivery_id(self, delivery_id: str) -> Run | None: ...
    def get_active_by_issue_key(self, issue_key: str) -> Run | None: ...
    def expire_leases(self, lease_seconds: int) -> int: ...
    def claim_next(self, workspace: str, lease_seconds: int) -> Run | None: ...


_ACTIVE = {
    RunStatus.received,
    RunStatus.triaged,
    RunStatus.queued,
    *IN_FLIGHT,
    RunStatus.berthing,
}


def _lease_stale(run: Run, cutoff: datetime) -> bool:
    if run.status not in IN_FLIGHT:
        return False
    stamp = run.last_progress_at or run.updated_at
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp < cutoff


def _expire_runs(runs: list[Run], lease_seconds: int) -> int:
    cutoff = datetime.now(UTC) - timedelta(seconds=lease_seconds)
    expired = 0
    for run in runs:
        if _lease_stale(run, cutoff):
            run.status = RunStatus.queued
            run.claimed_by = ""
            expired += 1
    return expired


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

    def get_by_delivery_id(self, delivery_id: str) -> Run | None:
        if not delivery_id:
            return None
        for run in self._runs.values():
            if run.delivery_id == delivery_id:
                return run
        return None

    def get_active_by_issue_key(self, issue_key: str) -> Run | None:
        for run in self._runs.values():
            if run.issue.key == issue_key and run.status in QUEUED_OR_IN_FLIGHT:
                return run
        return None

    def expire_leases(self, lease_seconds: int) -> int:
        expired = _expire_runs(list(self._runs.values()), lease_seconds)
        for run in self._runs.values():
            if run.status is RunStatus.queued and not run.claimed_by:
                run.touch()
        return expired

    def claim_next(self, workspace: str, lease_seconds: int) -> Run | None:
        self.expire_leases(lease_seconds)
        queued = sorted(
            [run for run in self._runs.values() if run.status is RunStatus.queued],
            key=lambda run: run.created_at,
        )
        if not queued:
            return None
        run = queued[0]
        run.status = RunStatus.claimed
        run.claimed_by = workspace
        run.last_progress_at = datetime.now(UTC)
        return self.put(run)


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
            self._migrate(conn)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
        if "delivery_id" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN delivery_id TEXT")
        if "issue_key" not in cols:
            conn.execute("ALTER TABLE runs ADD COLUMN issue_key TEXT")
        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_delivery_id
            ON runs(delivery_id)
            WHERE delivery_id IS NOT NULL AND delivery_id != ''
            """
        )

    def _upsert(self, conn: sqlite3.Connection, run: Run) -> None:
        run.touch()
        conn.execute(
            """
            INSERT INTO runs (id, payload, status, created_at, delivery_id, issue_key)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                payload = excluded.payload,
                status = excluded.status,
                delivery_id = excluded.delivery_id,
                issue_key = excluded.issue_key
            """,
            (
                run.id,
                run.model_dump_json(),
                run.status.value,
                run.created_at.isoformat(),
                run.delivery_id or None,
                run.issue.key,
            ),
        )

    def put(self, run: Run) -> Run:
        with self._connect() as conn:
            self._upsert(conn, run)
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

    def get_by_delivery_id(self, delivery_id: str) -> Run | None:
        if not delivery_id:
            return None
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM runs WHERE delivery_id = ?",
                (delivery_id,),
            ).fetchone()
        if row is None:
            return None
        return Run.model_validate(json.loads(row["payload"]))

    def get_active_by_issue_key(self, issue_key: str) -> Run | None:
        statuses = [s.value for s in QUEUED_OR_IN_FLIGHT]
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as conn:
            row = conn.execute(
                f"SELECT payload FROM runs WHERE issue_key = ? AND status IN ({placeholders})",
                (issue_key, *statuses),
            ).fetchone()
        if row is None:
            return None
        return Run.model_validate(json.loads(row["payload"]))

    def expire_leases(self, lease_seconds: int) -> int:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute("SELECT payload FROM runs").fetchall()
            runs = [Run.model_validate(json.loads(row["payload"])) for row in rows]
            expired = _expire_runs(runs, lease_seconds)
            for run in runs:
                if run.status is RunStatus.queued and not run.claimed_by:
                    self._upsert(conn, run)
            conn.commit()
        return expired

    def claim_next(self, workspace: str, lease_seconds: int) -> Run | None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute("SELECT payload FROM runs").fetchall()
            runs = [Run.model_validate(json.loads(row["payload"])) for row in rows]
            _expire_runs(runs, lease_seconds)
            for run in runs:
                self._upsert(conn, run)
            queued = sorted(
                [run for run in runs if run.status is RunStatus.queued],
                key=lambda run: run.created_at,
            )
            if not queued:
                conn.commit()
                return None
            run = queued[0]
            run.status = RunStatus.claimed
            run.claimed_by = workspace
            run.last_progress_at = datetime.now(UTC)
            self._upsert(conn, run)
            conn.commit()
            return run


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
