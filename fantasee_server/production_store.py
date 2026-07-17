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

from fantasee_server.shot_planning import ShotSpec


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


@dataclass(frozen=True)
class ProductionWorkerRecord:
    id: str
    capabilities: tuple[str, ...]
    status: str
    current_job_id: str | None
    last_seen: float
    created_at: float


@dataclass(frozen=True)
class ProductionAsset:
    id: str
    story_id: str
    scene_id: str
    asset_type: str
    path: str
    content_hash: str | None
    generation_fingerprint: str
    status: str
    metadata: dict[str, Any]
    supersedes: str | None
    created_at: float


@dataclass(frozen=True)
class ProductionShot:
    id: str
    story_id: str
    scene_id: str
    revision: int
    order: int
    purpose: str
    shot_type: str
    duration_seconds: float
    visual_context: str
    created_at: float


@dataclass(frozen=True)
class ProductionRelease:
    id: str
    story_id: str
    release_type: str
    fingerprint: str
    status: str
    path: str
    created_at: float


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
            CREATE TABLE IF NOT EXISTS production_workers (
                id TEXT PRIMARY KEY,
                capabilities_json TEXT NOT NULL,
                status TEXT NOT NULL,
                current_job_id TEXT,
                last_seen REAL NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS production_assets (
                id TEXT PRIMARY KEY,
                story_id TEXT NOT NULL,
                scene_id TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                path TEXT NOT NULL,
                content_hash TEXT,
                generation_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                supersedes TEXT,
                created_at REAL NOT NULL,
                UNIQUE (story_id, scene_id, asset_type, generation_fingerprint)
            );
            CREATE INDEX IF NOT EXISTS idx_production_assets_current
                ON production_assets(story_id, scene_id, asset_type, status);
            CREATE TABLE IF NOT EXISTS production_shots (
                story_id TEXT NOT NULL,
                scene_id TEXT NOT NULL,
                revision INTEGER NOT NULL,
                id TEXT NOT NULL,
                shot_order INTEGER NOT NULL,
                purpose TEXT NOT NULL,
                shot_type TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                visual_context TEXT NOT NULL,
                created_at REAL NOT NULL,
                PRIMARY KEY (story_id, scene_id, revision, id)
            );
            CREATE INDEX IF NOT EXISTS idx_production_shots_current
                ON production_shots(story_id, scene_id, revision, shot_order);
            CREATE TABLE IF NOT EXISTS production_releases (
                id TEXT PRIMARY KEY,
                story_id TEXT NOT NULL,
                release_type TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                path TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_production_releases_current
                ON production_releases(story_id, release_type, status, created_at);
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

    def list_runs(self, *, limit: int = 50) -> list[ProductionRun]:
        rows = self.connection.execute(
            """
            SELECT * FROM production_runs
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (max(1, min(200, int(limit))),),
        ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def update_run(self, run_id: str, *, status: str) -> ProductionRun:
        now = time.time()
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE production_runs SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, now, run_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"production run not found: {run_id}")
        return self.get_run(run_id)

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
        job_id: str | None = None,
        job_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        required_capabilities: tuple[str, ...] = (),
    ) -> ProductionJob:
        now = time.time()
        job_id = job_id or uuid.uuid4().hex
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

    def list_jobs(self, run_id: str) -> list[ProductionJob]:
        rows = self.connection.execute(
            """
            SELECT * FROM production_jobs
            WHERE run_id = ?
            ORDER BY created_at, id
            """,
            (run_id,),
        ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def list_runnable_jobs(self) -> list[ProductionJob]:
        rows = self.connection.execute(
            """
            SELECT * FROM production_jobs
            WHERE status IN ('queued', 'retryable') AND available_at <= ?
            ORDER BY created_at, id
            """,
            (time.time(),),
        ).fetchall()
        return [self._job_from_row(row) for row in rows]

    def register_worker(self, worker_id: str, capabilities: tuple[str, ...]) -> ProductionWorkerRecord:
        now = time.time()
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO production_workers
                    (id, capabilities_json, status, last_seen, created_at)
                VALUES (?, ?, 'idle', ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    capabilities_json = excluded.capabilities_json,
                    status = 'idle', current_job_id = NULL, last_seen = excluded.last_seen
                """,
                (worker_id, json.dumps(sorted(set(capabilities))), now, now),
            )
        return self.get_worker(worker_id)

    def get_worker(self, worker_id: str) -> ProductionWorkerRecord | None:
        row = self.connection.execute(
            "SELECT * FROM production_workers WHERE id = ?", (worker_id,)
        ).fetchone()
        return self._worker_from_row(row) if row else None

    def list_workers(self) -> list[ProductionWorkerRecord]:
        rows = self.connection.execute(
            "SELECT * FROM production_workers ORDER BY id"
        ).fetchall()
        return [self._worker_from_row(row) for row in rows]

    def update_worker(
        self,
        worker_id: str,
        *,
        status: str,
        current_job_id: str | None = None,
    ) -> ProductionWorkerRecord:
        now = time.time()
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE production_workers
                SET status = ?, current_job_id = ?, last_seen = ?
                WHERE id = ?
                """,
                (status, current_job_id, now, worker_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"production worker not found: {worker_id}")
        return self.get_worker(worker_id)

    def register_asset(
        self,
        *,
        story_id: str,
        scene_id: str,
        asset_type: str,
        path: str,
        generation_fingerprint: str,
        content_hash: str | None = None,
        metadata: dict[str, Any] | None = None,
        supersedes: str | None = None,
        asset_id: str | None = None,
    ) -> ProductionAsset:
        now = time.time()
        asset_id = asset_id or uuid.uuid4().hex
        with self.connection:
            self.connection.execute(
                """
                INSERT INTO production_assets
                    (id, story_id, scene_id, asset_type, path, content_hash,
                     generation_fingerprint, status, metadata_json, supersedes, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'candidate', ?, ?, ?)
                ON CONFLICT (story_id, scene_id, asset_type, generation_fingerprint) DO NOTHING
                """,
                (asset_id, story_id, scene_id, asset_type, path, content_hash,
                 generation_fingerprint, json.dumps(metadata or {}), supersedes, now),
            )
        row = self.connection.execute(
            """
            SELECT * FROM production_assets
            WHERE story_id = ? AND scene_id = ? AND asset_type = ?
              AND generation_fingerprint = ?
            """,
            (story_id, scene_id, asset_type, generation_fingerprint),
        ).fetchone()
        return self._asset_from_row(row)

    def get_asset(self, asset_id: str) -> ProductionAsset | None:
        row = self.connection.execute(
            "SELECT * FROM production_assets WHERE id = ?", (asset_id,)
        ).fetchone()
        return self._asset_from_row(row) if row else None

    def list_assets(self, story_id: str) -> list[ProductionAsset]:
        rows = self.connection.execute(
            "SELECT * FROM production_assets WHERE story_id = ? ORDER BY created_at, id",
            (story_id,),
        ).fetchall()
        return [self._asset_from_row(row) for row in rows]

    def record_release(
        self,
        story_id: str,
        *,
        release_type: str,
        fingerprint: str,
        path: str,
        status: str = "current",
    ) -> ProductionRelease:
        now = time.time()
        release_id = uuid.uuid4().hex
        with self.connection:
            if status == "current":
                self.connection.execute(
                    "UPDATE production_releases SET status = 'superseded' "
                    "WHERE story_id = ? AND release_type = ? AND status = 'current'",
                    (story_id, release_type),
                )
            self.connection.execute(
                """INSERT INTO production_releases
                    (id, story_id, release_type, fingerprint, status, path, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (release_id, story_id, release_type, fingerprint, status, path, now),
            )
        return self.get_release(release_id)

    def get_release(self, release_id: str) -> ProductionRelease | None:
        row = self.connection.execute(
            "SELECT * FROM production_releases WHERE id = ?", (release_id,)
        ).fetchone()
        return self._release_from_row(row) if row else None

    def get_current_release(self, story_id: str, release_type: str) -> ProductionRelease | None:
        row = self.connection.execute(
            """SELECT * FROM production_releases
               WHERE story_id = ? AND release_type = ? AND status = 'current'
               ORDER BY created_at DESC, id DESC LIMIT 1""",
            (story_id, release_type),
        ).fetchone()
        return self._release_from_row(row) if row else None

    def list_releases(self, story_id: str) -> list[ProductionRelease]:
        rows = self.connection.execute(
            "SELECT * FROM production_releases WHERE story_id = ? ORDER BY created_at DESC, id DESC",
            (story_id,),
        ).fetchall()
        return [self._release_from_row(row) for row in rows]

    def save_shot_plan(
        self, story_id: str, scene_id: str, shots: list[ShotSpec]
    ) -> int:
        """Persist an immutable ordered revision for one scene's visual plan."""
        now = time.time()
        with self.connection:
            revision = self.connection.execute(
                """
                SELECT COALESCE(MAX(revision), 0) + 1
                FROM production_shots WHERE story_id = ? AND scene_id = ?
                """,
                (story_id, scene_id),
            ).fetchone()[0]
            self.connection.executemany(
                """
                INSERT INTO production_shots
                    (story_id, scene_id, revision, id, shot_order, purpose, shot_type,
                     duration_seconds, visual_context, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (story_id, scene_id, revision, shot.id, shot.order, shot.purpose,
                     shot.shot_type, shot.duration_seconds, shot.visual_context, now)
                    for shot in shots
                ],
            )
        return revision

    def list_shots(
        self, story_id: str, scene_id: str, *, revision: int | None = None
    ) -> list[ProductionShot]:
        if revision is None:
            revision = self.connection.execute(
                """
                SELECT MAX(revision) FROM production_shots
                WHERE story_id = ? AND scene_id = ?
                """,
                (story_id, scene_id),
            ).fetchone()[0]
        if revision is None:
            return []
        rows = self.connection.execute(
            """
            SELECT * FROM production_shots
            WHERE story_id = ? AND scene_id = ? AND revision = ?
            ORDER BY shot_order, id
            """,
            (story_id, scene_id, revision),
        ).fetchall()
        return [self._shot_from_row(row) for row in rows]

    def revise_shot(
        self,
        story_id: str,
        scene_id: str,
        shot_id: str,
        *,
        visual_context: str,
    ) -> int:
        """Copy the current plan into a new revision with one revised shot."""
        current = self.list_shots(story_id, scene_id)
        if not current or not any(shot.id == shot_id for shot in current):
            raise ValueError(f"shot not found: {shot_id}")
        revised = [
            ShotSpec(
                id=shot.id,
                scene_id=shot.scene_id,
                order=shot.order,
                purpose=shot.purpose,
                shot_type=shot.shot_type,
                duration_seconds=shot.duration_seconds,
                visual_context=visual_context if shot.id == shot_id else shot.visual_context,
            )
            for shot in current
        ]
        return self.save_shot_plan(story_id, scene_id, revised)

    def restore_shot_plan_revision(
        self, story_id: str, scene_id: str, *, revision: int
    ) -> int:
        """Make an earlier immutable plan current by copying it to a new revision."""
        previous = self.list_shots(story_id, scene_id, revision=revision)
        if not previous:
            raise ValueError(f"shot plan revision not found: {revision}")
        return self.save_shot_plan(
            story_id,
            scene_id,
            [
                ShotSpec(
                    id=shot.id,
                    scene_id=shot.scene_id,
                    order=shot.order,
                    purpose=shot.purpose,
                    shot_type=shot.shot_type,
                    duration_seconds=shot.duration_seconds,
                    visual_context=shot.visual_context,
                )
                for shot in previous
            ],
        )

    def list_shot_plan_revisions(self, story_id: str, scene_id: str) -> list[int]:
        rows = self.connection.execute(
            """
            SELECT DISTINCT revision FROM production_shots
            WHERE story_id = ? AND scene_id = ?
            ORDER BY revision DESC
            """,
            (story_id, scene_id),
        ).fetchall()
        return [row["revision"] for row in rows]

    def get_current_asset(
        self, story_id: str, scene_id: str, asset_type: str
    ) -> ProductionAsset | None:
        row = self.connection.execute(
            """
            SELECT * FROM production_assets
            WHERE story_id = ? AND scene_id = ? AND asset_type = ? AND status = 'approved'
            ORDER BY created_at DESC, id DESC LIMIT 1
            """,
            (story_id, scene_id, asset_type),
        ).fetchone()
        return self._asset_from_row(row) if row else None

    def approve_asset(self, asset_id: str) -> ProductionAsset:
        with self.connection:
            candidate = self.connection.execute(
                "SELECT * FROM production_assets WHERE id = ?", (asset_id,)
            ).fetchone()
            if candidate is None:
                raise ValueError(f"production asset not found: {asset_id}")
            self.connection.execute(
                """
                UPDATE production_assets SET status = 'superseded'
                WHERE story_id = ? AND scene_id = ? AND asset_type = ?
                  AND status = 'approved' AND id != ?
                """,
                (candidate["story_id"], candidate["scene_id"], candidate["asset_type"], asset_id),
            )
            self.connection.execute(
                "UPDATE production_assets SET status = 'approved' WHERE id = ?",
                (asset_id,),
            )
        return self.get_asset(asset_id)

    def lease_next_job(
        self,
        worker_id: str,
        *,
        lease_seconds: float = 60,
        capabilities: tuple[str, ...] = (),
        job_types: tuple[str, ...] = (),
        run_id: str | None = None,
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
            query = """
                SELECT * FROM production_jobs
                WHERE status IN ('queued', 'retryable') AND available_at <= ?
            """
            params: tuple[Any, ...] = (now,)
            if run_id:
                query += " AND run_id = ?"
                params += (run_id,)
            candidates = self.connection.execute(query + " ORDER BY created_at, id", params).fetchall()
            worker_capabilities = set(capabilities)
            accepted_job_types = set(job_types)
            row = next(
                (
                    candidate
                    for candidate in candidates
                    if (not accepted_job_types or candidate["job_type"] in accepted_job_types)
                    and set(json.loads(candidate["required_capabilities_json"])).issubset(
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
                WHERE id = ? AND status IN ('queued', 'retryable')
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

    def start_job(self, job_id: str, lease_token: str | None) -> ProductionJob:
        now = time.time()
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE production_jobs SET status = 'running', updated_at = ?
                WHERE id = ? AND status = 'leased' AND lease_token = ?
                """,
                (now, job_id, lease_token),
            )
        if cursor.rowcount != 1:
            raise ValueError("job lease is invalid or has expired")
        return self.get_job(job_id)

    def heartbeat(
        self, job_id: str, lease_token: str | None, *, lease_seconds: float = 60
    ) -> ProductionJob:
        now = time.time()
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE production_jobs
                SET status = 'running', lease_expires_at = ?, updated_at = ?
                WHERE id = ? AND status IN ('leased', 'running') AND lease_token = ?
                """,
                (now + lease_seconds, now, job_id, lease_token),
            )
        if cursor.rowcount != 1:
            raise ValueError("job lease is invalid or has expired")
        return self.get_job(job_id)

    def update_job_progress(
        self,
        job_id: str,
        lease_token: str | None,
        *,
        progress: float,
        message: str | None = None,
    ) -> ProductionJob:
        now = time.time()
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE production_jobs SET progress = ?, message = ?, updated_at = ?
                WHERE id = ? AND status IN ('leased', 'running') AND lease_token = ?
                """,
                (max(0.0, min(1.0, float(progress))), message, now, job_id, lease_token),
            )
        if cursor.rowcount != 1:
            raise ValueError("job lease is invalid or has expired")
        return self.get_job(job_id)

    def fail_job(
        self,
        job_id: str,
        lease_token: str | None,
        *,
        message: str,
        retryable: bool = True,
        retry_delay: float = 0,
    ) -> ProductionJob:
        now = time.time()
        status = "retryable" if retryable else "failed"
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE production_jobs
                SET status = ?, message = ?, available_at = ?,
                    lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                    updated_at = ?
                WHERE id = ? AND status IN ('leased', 'running') AND lease_token = ?
                """,
                (status, message, now + max(0, retry_delay), now, job_id, lease_token),
            )
        if cursor.rowcount != 1:
            raise ValueError("job lease is invalid or has expired")
        return self.get_job(job_id)

    def set_job_status(
        self,
        job_id: str,
        *,
        status: str,
        progress: float = 0,
        message: str | None = None,
    ) -> ProductionJob:
        now = time.time()
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE production_jobs
                SET status = ?, progress = ?, message = ?, available_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (status, progress, message, now, now, job_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"production job not found: {job_id}")
        return self.get_job(job_id)

    def cancel_job(self, job_id: str) -> ProductionJob:
        now = time.time()
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE production_jobs
                SET status = 'cancelled', message = 'Cancelled by operator',
                    lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                    updated_at = ?
                WHERE id = ? AND status IN ('queued', 'retryable', 'leased', 'running')
                """,
                (now, job_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"job cannot be cancelled: {job_id}")
        return self.get_job(job_id)

    def retry_job(self, job_id: str) -> ProductionJob:
        now = time.time()
        with self.connection:
            cursor = self.connection.execute(
                """
                UPDATE production_jobs
                SET status = 'queued', message = 'Queued for retry', available_at = ?,
                    lease_owner = NULL, lease_token = NULL, lease_expires_at = NULL,
                    updated_at = ?
                WHERE id = ? AND status IN ('failed', 'cancelled', 'retryable')
                """,
                (now, now, job_id),
            )
        if cursor.rowcount != 1:
            raise ValueError(f"job cannot be retried: {job_id}")
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

    @staticmethod
    def _worker_from_row(row: sqlite3.Row) -> ProductionWorkerRecord:
        return ProductionWorkerRecord(
            id=row["id"],
            capabilities=tuple(json.loads(row["capabilities_json"])),
            status=row["status"],
            current_job_id=row["current_job_id"],
            last_seen=row["last_seen"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _asset_from_row(row: sqlite3.Row) -> ProductionAsset:
        return ProductionAsset(
            id=row["id"],
            story_id=row["story_id"],
            scene_id=row["scene_id"],
            asset_type=row["asset_type"],
            path=row["path"],
            content_hash=row["content_hash"],
            generation_fingerprint=row["generation_fingerprint"],
            status=row["status"],
            metadata=json.loads(row["metadata_json"]),
            supersedes=row["supersedes"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _shot_from_row(row: sqlite3.Row) -> ProductionShot:
        return ProductionShot(
            id=row["id"],
            story_id=row["story_id"],
            scene_id=row["scene_id"],
            revision=row["revision"],
            order=row["shot_order"],
            purpose=row["purpose"],
            shot_type=row["shot_type"],
            duration_seconds=row["duration_seconds"],
            visual_context=row["visual_context"],
            created_at=row["created_at"],
        )

    @staticmethod
    def _release_from_row(row: sqlite3.Row) -> ProductionRelease:
        return ProductionRelease(
            id=row["id"], story_id=row["story_id"], release_type=row["release_type"],
            fingerprint=row["fingerprint"], status=row["status"], path=row["path"],
            created_at=row["created_at"],
        )

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "ProductionStore":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()
