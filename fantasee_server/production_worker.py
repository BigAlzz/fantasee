"""Lease-based execution for durable production jobs."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any, Callable

from fantasee_server.production_store import ProductionJob, ProductionStore


class ProductionWorker:
    """Claim and execute one job without allowing stale workers to overwrite it."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        worker_id: str,
        capabilities: tuple[str, ...] = (),
        lease_seconds: float = 60,
        heartbeat_seconds: float | None = None,
        max_attempts: int = 3,
    ):
        self.database_path = Path(database_path)
        self.worker_id = worker_id
        self.capabilities = capabilities
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds or max(1.0, lease_seconds / 3)
        self.max_attempts = max(1, max_attempts)

    def _store(self) -> ProductionStore:
        return ProductionStore(self.database_path)

    async def run_once(
        self,
        handler: Callable[[ProductionJob, Callable[[str, str, float], None]], Any],
    ) -> bool:
        with self._store() as store:
            store.register_worker(self.worker_id, self.capabilities)
            job = store.lease_next_job(
                self.worker_id,
                lease_seconds=self.lease_seconds,
                capabilities=self.capabilities,
            )
            if job is None:
                store.update_worker(self.worker_id, status="idle")
                return False
            token = job.lease_token
            store.start_job(job.id, token)
            store.update_worker(self.worker_id, status="running", current_job_id=job.id)

        heartbeat_task = asyncio.create_task(self._heartbeat(job.id, token))

        def progress(stage: str, message: str, value: float) -> None:
            try:
                with self._store() as store:
                    store.update_job_progress(
                        job.id,
                        token,
                        progress=value,
                        message=f"{stage}: {message}",
                    )
            except ValueError:
                # The lease may have expired and been reclaimed. The stale
                # worker must not mutate the replacement worker's job.
                pass

        try:
            if inspect.iscoroutinefunction(handler):
                result = handler(job, progress)
            else:
                result = await asyncio.to_thread(handler, job, progress)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            heartbeat_task.cancel()
            await self._finish_heartbeat(heartbeat_task)
            with self._store() as store:
                store.fail_job(
                    job.id,
                    token,
                    message=str(exc),
                    retryable=job.attempts < self.max_attempts,
                    retry_delay=min(60, 2 ** max(0, job.attempts - 1)),
                )
                store.update_worker(self.worker_id, status="idle")
            return True

        heartbeat_task.cancel()
        await self._finish_heartbeat(heartbeat_task)
        with self._store() as store:
            store.complete_job(job.id, token, output=result if isinstance(result, dict) else None)
            store.update_worker(self.worker_id, status="idle")
        return True

    async def _heartbeat(self, job_id: str, token: str | None) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            try:
                with self._store() as store:
                    store.heartbeat(job_id, token, lease_seconds=self.lease_seconds)
                    store.update_worker(self.worker_id, status="running", current_job_id=job_id)
            except ValueError:
                return

    @staticmethod
    async def _finish_heartbeat(task: asyncio.Task) -> None:
        try:
            await task
        except asyncio.CancelledError:
            pass
