"""
main.py — Job application processing loop.

Dequeues jobs one by one and runs each through the LangGraph pipeline.
Loads the candidate profile once and passes it through all jobs.
"""
from __future__ import annotations

import asyncio
import argparse
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()


async def run(user_id: int = 1) -> None:
    from database.connection import init_db, get_session_factory
    from database.models import User
    from queue.manager import JobQueueManager
    from agents.graph import build_graph
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    init_db()
    session_factory = get_session_factory()
    queue = JobQueueManager(session_factory)
    graph = build_graph()

    # Load candidate profile once — shared across all jobs in this run
    profile = None
    with session_factory() as session:
        user = session.execute(
            select(User)
            .options(
                selectinload(User.work_experiences),
                selectinload(User.educations),
                selectinload(User.skills),
                selectinload(User.custom_answers),
            )
            .where(User.id == user_id)
        ).scalar_one_or_none()

        if not user:
            print(f"[Agent] No user found with id={user_id}. Run: python demo.py --seed-only")
            return
        profile = user.to_dict()
        print(f"[Agent] Loaded profile: {profile['full_name']} ({profile['email']})")

    # Print queue stats
    stats = queue.get_stats()
    queued = stats.get("queued", 0)
    print(f"[Agent] Queue — {queued} job(s) ready")
    if queued == 0:
        print("[Agent] Nothing to process. Add jobs via queue.add_job() or re-seed.")
        return

    print("[Agent] Starting pipeline...\n")

    processed = 0
    while True:
        job = queue.dequeue_next()
        if not job:
            print(f"\n[Agent] Queue empty. Processed {processed} job(s) this run.")
            break

        print(f"[Agent] ── [{processed + 1}/{queued}] {job.company or 'Unknown'} — {job.title or 'Unknown Role'}")
        print(f"         {job.url}")
        print(f"         ATS: {job.ats_platform or 'detecting...'}")

        started = datetime.utcnow()

        initial_state: dict = {
            "job_id": job.id,
            "job_url": job.url,
            "user_id": user_id,
            "user_profile": profile,
            "status": "processing",
            "unanswered_fields": [],
            "retry_count": 0,
            "messages": [],
            "browser_ready": False,
            "job_title": job.title,
            "job_company": job.company,
            "job_description": None,
            "ats_platform": job.ats_platform,
            "tailored_resume": None,
            "cover_letter": None,
            "current_page_url": None,
            "form_fields": None,
            "resolved_fields": None,
            "pending_hitl_field": None,
            "error": None,
            "started_at": started.isoformat(),
        }

        try:
            result = await graph.ainvoke(initial_state)
            elapsed = (datetime.utcnow() - started).seconds
            status = result.get("status", "unknown")
            icon = {"submitted": "✓", "backlog": "⚠", "failed": "✗"}.get(status, "?")
            print(f"         {icon} {status.upper()} ({elapsed}s)\n")
        except Exception as exc:
            print(f"         ✗ CRASHED: {exc}\n")
            queue.mark_failed(job.id, str(exc))

        processed += 1


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Job Application Agent")
    parser.add_argument("--user-id", type=int, default=1, help="Candidate user ID (default: 1)")
    args = parser.parse_args()
    asyncio.run(run(user_id=args.user_id))


if __name__ == "__main__":
    main()
