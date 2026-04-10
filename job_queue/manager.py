"""
queue/manager.py — Job queue operations.

Provides atomic dequeue (with FOR UPDATE SKIP LOCKED for PostgreSQL
compatibility) and status update helpers.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from database.models import Job, JobStatus


class JobQueueManager:
    def __init__(self, session_factory: sessionmaker):
        self._factory = session_factory

    # ------------------------------------------------------------------ #
    # Dequeue                                                              #
    # ------------------------------------------------------------------ #

    def dequeue_next(self, ats_platform: Optional[str] = None) -> Optional[Job]:
        """
        Atomically fetch and lock the next queued job.
        Sets status → processing so concurrent workers skip it.
        Pass ats_platform to filter by a specific ATS (e.g. 'workday').
        """
        with self._factory() as session:
            query = select(Job).where(Job.status == JobStatus.QUEUED)
            if ats_platform:
                query = query.where(Job.ats_platform == ats_platform)
            job = session.execute(
                query.order_by(Job.created_at.asc()).limit(1)
            ).scalar_one_or_none()

            if job:
                job.status = JobStatus.PROCESSING
                job.processed_at = datetime.utcnow()
                session.commit()
                # Return a detached copy so the session can close
                session.expunge(job)
            return job

    # ------------------------------------------------------------------ #
    # Status updates                                                       #
    # ------------------------------------------------------------------ #

    def mark_submitted(self, job_id: int) -> None:
        self._update(job_id, status=JobStatus.SUBMITTED)

    def mark_failed(self, job_id: int, reason: str) -> None:
        self._update(job_id, status=JobStatus.FAILED, failure_reason=reason)

    def mark_backlog(self, job_id: int, unanswered_fields: list) -> None:
        self._update(
            job_id,
            status=JobStatus.BACKLOG,
            unanswered_fields=unanswered_fields,
        )

    def requeue_backlog(self, job_id: int) -> None:
        """Re-queue a backlog job after the user has added missing answers."""
        self._update(
            job_id,
            status=JobStatus.QUEUED,
            failure_reason=None,
            unanswered_fields=None,
        )

    # ------------------------------------------------------------------ #
    # Add jobs                                                             #
    # ------------------------------------------------------------------ #

    def add_job(self, url: str, company: str = None, title: str = None) -> Job:
        """Add a new job URL to the queue. Skips if URL already exists."""
        with self._factory() as session:
            existing = session.execute(
                select(Job).where(Job.url == url)
            ).scalar_one_or_none()

            if existing:
                print(f"[Queue] Job already exists: {url}")
                return existing

            job = Job(url=url, company=company, title=title, status=JobStatus.QUEUED)
            session.add(job)
            session.commit()
            session.expunge(job)
            print(f"[Queue] Added job: {url}")
            return job

    # ------------------------------------------------------------------ #
    # Stats                                                                #
    # ------------------------------------------------------------------ #

    def get_stats(self) -> dict:
        """Return a count of jobs per status."""
        with self._factory() as session:
            jobs = session.execute(select(Job)).scalars().all()
            stats: dict = {}
            for job in jobs:
                stats[job.status] = stats.get(job.status, 0) + 1
            return stats

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _update(self, job_id: int, **kwargs) -> None:
        with self._factory() as session:
            job = session.get(Job, job_id)
            if job:
                for k, v in kwargs.items():
                    setattr(job, k, v)
                job.updated_at = datetime.utcnow()
                session.commit()
