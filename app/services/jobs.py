"""Transactional-outbox style background jobs with retries, exponential backoff and a failure alert."""
from __future__ import annotations

import json
import logging
import threading
from typing import Callable

from sqlalchemy.engine import Engine

from app.config import Settings
from app.repositories import JobRepo
from app.utils import iso_in, new_id, now_iso

logger = logging.getLogger(__name__)


class JobRunner:
    def __init__(self, engine: Engine, settings: Settings, handlers: dict[str, Callable[[dict], object]]):
        self.engine, self.s, self.handlers = engine, settings, handlers

    def enqueue(self, type: str, payload: dict, tenant_id: str | None = None) -> str:
        job_id = new_id()
        with self.engine.begin() as conn:
            JobRepo.enqueue(conn, job_id, tenant_id, type, json.dumps(payload), self.s.job_max_attempts, now_iso())
        return job_id

    def run_once(self, limit: int = 10) -> int:
        with self.engine.begin() as conn:
            jobs = JobRepo.claim_due(conn, now_iso(), limit)
        for job in jobs:
            try:
                self.handlers[job["type"]](json.loads(job["payload_json"]))
            except Exception as exc:
                self._on_failure(job, exc)
            else:
                with self.engine.begin() as conn:
                    JobRepo.mark_done(conn, job["id"], now_iso())
        return len(jobs)

    def _on_failure(self, job: dict, exc: Exception) -> None:
        attempts, err = job["attempts"] + 1, f"{type(exc).__name__}: {exc}"[:500]
        with self.engine.begin() as conn:
            if attempts >= job["max_attempts"]:
                JobRepo.mark_failed(conn, job["id"], attempts, err, now_iso())
                # Failure alert: loud log line (plug a webhook/pager in here) + visible via /dashboard/jobs/failed
                logger.error("ALERT job %s (%s) permanently failed after %d attempts: %s", job["id"], job["type"], attempts, err)
            else:
                delay = self.s.job_backoff_base_seconds ** attempts
                JobRepo.mark_retry(conn, job["id"], attempts, iso_in(delay), err, now_iso())
                logger.warning("job %s (%s) failed (attempt %d/%d), retry in %.1fs: %s", job["id"], job["type"], attempts, job["max_attempts"], delay, err)


class Worker:
    def __init__(self, runner: JobRunner, poll_seconds: float):
        self.runner, self.poll = runner, poll_seconds
        self._stop, self._thread = threading.Event(), None

    def start(self) -> None:
        with self.runner.engine.begin() as conn:
            JobRepo.requeue_stuck(conn, now_iso())  # recover jobs interrupted by a crash
        self._thread = threading.Thread(target=self._loop, name="job-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                n = self.runner.run_once()
            except Exception:
                logger.exception("worker loop error")
                n = 0
            if n == 0:
                self._stop.wait(self.poll)
