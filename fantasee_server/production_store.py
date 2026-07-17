"""Durable state for story production runs and their event history.

This module intentionally exposes a small domain seam.  The queue and API can
depend on it without knowing whether the backing store is SQLite or a later
server database.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProductionRun:
    id: str
    story_id: str
    command: str
    input_fingerprint: str
    status: str
    created_at: float
    updated_at: float


@dataclass(frozen=True)
class ProductionEvent:
    run_id: str
    sequence: int
    event_type: str
    payload: dict[str, Any]
    created_at: float


@dataclass(frozen=True)
class ProductionJob:
    id: str
    run_id: str
    job_type: str
    payload: dict[str, Any]
    idempotency_key: str
    required_capabilities: tuple[str, ...]
    status: str
    attempts: int
    progress: float
    message: str | None
    lease_owner: str | None
    lease_token: str | None
    lease_expires_at: float | None


class ProductionStore:
    """SQLite implementation of the durable production state seam."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.database_path, timeout=5)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA busy_timeout = 5000")
        self._create_schema()

    def _create_schema(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS production_runs (
                id TEXT PRIMARY KEY,
                story_id TEXT NOT NULL,
                command TEXT NOT NULL,
                input_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS production_events (
                run_id TEXT NOT NULL REFERENCES production_runs(id) ON DELETE CASCADE,
                sequence INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (run_id, sequence)
            );
            CREATE INDEX IF NOT EXISTS idx_production_events_run
                ON production_events(run_id, sequence);
            CREATE TABLE IF NOT EXISTS production_jobs (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES production_runs(id) ON DELETE CASCADE,
                job_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                idempotency_key TEXT NOT NULL,
                required_capabilities_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                progress REAL NOT NULL DEFAULT 0,
                message TEXT,
                lease_owner TEXT,
                lease_token TEXT,
                lease_expires_at REAL,
                available_at REAL NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE (run_id, idempotency_key)
            );
            CREATE INDEX IF NOT EXISTS idx_production_jobs_available
                ON production_jobs(status, available_at);
            """
        )
        self.connection.commit()

    def create_run(
        self,
        *,
        story_id: str,
        command: str,
        input_fingerprint: str,
        run_id: str | None = None,
    ) -> ProductionRun:
        now = time.time()
        run_id = run_id or uuid.uuid4().hex
        self.connection.execute(
            """
            INSERT INTO production_runs
                (id, story_id, command, input_fingerprint, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'queued', ?, ?)
            """,
            (run_id, story_id, command, input_fingerprint, now, now),
        )
        self.connection.commit()
        return self._run_from_row(self.connection.execute(
            "SELECT * FROM production_runs WHERE id = ?", (run_id,)
        ).fetchone())

    def get_run(self, run_id: str) -> ProductionRun | None:
        row = self.connection.execute(
            "SELECT * FROM production_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return self._run_from_row(row) if row else None

    def append_event(
        self, run_id: str, event_type: str, payload: dict[str, Any]
    ) -> ProductionEvent:
        now = time.time()
        with self.connection:
            sequence = self.connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM production_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
            self.connection.execute(
                """
                INSERT INTO production_events
                    (run_id, sequence, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (run_id, sequence, event_type, json.dumps(payload), now),
            )
        return ProductionEvent(run_id, sequence, event_type, payload, now)

    def list_events(self, run_id: str, *, after_sequence: int = 0) -> list[ProductionEvent]:
        rows = self.connection.execute(
            """
            SELECT * FROM production_events
            WHERE run_id = ? AND sequence > ?
            ORDER BY sequence
            """,
            (run_id, after_sequence),
        ).fetchall()
        return [
            ProductionEvent(
                run_id=row["run_id"],
                sequence=row["sequence"],
                event_type=row["event_type"],
                payload=json.loads(row["payload_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def enqueue_job(
        self,
        run_id: str,
        *,
        job_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        required_capabilities: tuple[str, ...] = (),
    ) -> ProductionJob:
        now = time.time()
        job_id = uuid.uuid4().hex
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO production_jobs
                    (id, run_id, job_type, payload_json, idempotency_key,
                     required_capabilities_json, status, available_at, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)
                ON CONFLICT (run_id, idempotency_key) DO NOTHING
                """,
                (job_id, run_id, job_type, json.dumps(payload), idempotency_key,
                 json.dumps(sorted(set(required_capabilities))), now, now, now),
            )
        row = self.connection.execute(
            """
            SELECT * FROM production_jobs
            WHERE run_id = ? AND idempotency_key = ?
            """,
            (run_id, idempotency_key),
        ).fetchone()
        return self._job_from_row(row)

    def get_job(self, job_id: str) -> ProductionJob | None:
        row = self.connection.execute(
            "SELECT * FROM production_jobs WHERE id = ?", (job_id,)
        ).fetchone()
        return self._job_from_row(row) if row else None

    def lease_next_job(
        self,
        worker_id: str,
        *,
        lease_seconds: float = 60,
        capabilities: tuple[str, ...] = (),
        now: float | None = None,
    ) -> ProductionJob | None:
        now = time.time() if now is None else now
        lease_token = uuid.uuid4().hex
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            self.connection.execute(
                """
                UPDATE production_jobs
                SET status = 'queued', lease_owner = NULL, lease_token = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE status IN ('leased', 'running')
                  AND lease_expires_at IS NOT NULL
                  AND lease_expires_at <= ?
                """,
                (now, now),
            )
            candidates = self.connection.execute(
                """
                SELECT * FROM production_jobs
                WHERE status = 'queued' AND available_at <= ?
                ORDER BY created_at, id
                """,
                (now,),
            ).fetchall()
            worker_capabilities = set(capabilities)
            row = next(
                (
                    candidate
                    for candidate in candidates
                    if set(json.loads(candidate["required_capabilities_json"])).issubset(
                        worker_capabilities
                    )
                ),
                None,
            )
            if row is None:
                self.connection.commit()
                return None
            self.connection.execute(
                """
                UPDATE production_jobs
                SET status = 'leased', lease_owner = ?, lease_token = ?,
                    lease_expires_at = ?, attempts = attempts + 1, updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (worker_id, lease_token, now + lease_seconds, now, row["id"]),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        leased = self.get_job(row["id"])
        return leased

    def complete_job(
        self, job_id: str, lease_token: str | None, *, output: dict[str, Any] | None = None
    ) -> ProductionJob:
        now = time.time()
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE production_jobs
                SET status = 'succeeded', progress = 1, message = NULL,
                    lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                    updated_at = ?
                WHERE id = ? AND status IN ('leased', 'running') AND lease_token = ?
                """,
                (now, job_id, lease_token),
            )
        if cursor.rowcount != 1:
            raise ValueError("job lease is invalid or has expired")
        return self.get_job(job_id)

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> ProductionRun:
        return ProductionRun(
            id=row["id"],
            story_id=row["story_id"],
            command=row["command"],
            input_fingerprint=row["input_fingerprint"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _job_from_row(row: sqlite3.Row) -> ProductionJob:
        return ProductionJob(
            id=row["id"],
            run_id=row["run_id"],
            job_type=row["job_type"],
            payload=json.loads(row["payload_json"]),
            idempotency_key=row["idempotency_key"],
            required_capabilities=tuple(json.loads(row["required_capabilities_json"])),
            status=row["status"],
            attempts=row["attempts"],
            progress=row["progress"],
            message=row["message"],
            lease_owner=row["lease_owner"],
            lease_token=row["lease_token"],
            lease_expires_at=row["lease_expires_at"],
        )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "ProductionStore":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()
