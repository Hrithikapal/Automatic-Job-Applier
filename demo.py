"""
demo.py — Seed the demo profile and run the full pipeline.

Usage:
    python demo.py                  # seed + run full pipeline
    python demo.py --seed-only      # seed DB and generate resume PDF, then exit
    python demo.py --status         # print current job status table
    python demo.py --reset          # reset all jobs back to 'queued'
"""
from __future__ import annotations

import argparse
import asyncio

from dotenv import load_dotenv
load_dotenv()


# ---------------------------------------------------------------------------
# Status table printer
# ---------------------------------------------------------------------------

def print_status_table() -> None:
    from database.connection import init_db, get_session_factory
    from database.models import Job
    from sqlalchemy import select

    init_db()
    with get_session_factory()() as session:
        jobs = session.execute(select(Job).order_by(Job.id)).scalars().all()

    if not jobs:
        print("\n  No jobs in queue.\n")
        return

    print(f"\n{'─' * 95}")
    print(f"  {'ID':<4} {'Company':<18} {'Title':<32} {'ATS':<12} {'Status':<12} {'Updated'}")
    print(f"{'─' * 95}")
    status_icons = {
        "queued":     "○",
        "processing": "◉",
        "submitted":  "✓",
        "failed":     "✗",
        "backlog":    "⚠",
    }
    for job in jobs:
        company  = (job.company or "—")[:17]
        title    = (job.title or "—")[:31]
        ats      = (job.ats_platform or "—")[:11]
        icon     = status_icons.get(job.status, "?")
        updated  = job.updated_at.strftime("%H:%M:%S") if job.updated_at else "—"
        print(f"  {job.id:<4} {company:<18} {title:<32} {ats:<12} {icon} {job.status:<10} {updated}")
    print(f"{'─' * 95}\n")


# ---------------------------------------------------------------------------
# Reset helper
# ---------------------------------------------------------------------------

def reset_jobs() -> None:
    from database.connection import get_session_factory
    from database.models import Job, JobStatus
    from sqlalchemy import select

    with get_session_factory()() as session:
        jobs = session.execute(select(Job)).scalars().all()
        for job in jobs:
            job.status = JobStatus.QUEUED
            job.failure_reason = None
            job.unanswered_fields = None
        session.commit()
    print(f"[Demo] Reset {len(jobs)} job(s) to 'queued'.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="AI Job Application Agent — Demo Runner")
    parser.add_argument("--seed-only", action="store_true",
                        help="Seed DB and generate resume PDF, then exit")
    parser.add_argument("--status", action="store_true",
                        help="Print current job status table and exit")
    parser.add_argument("--reset", action="store_true",
                        help="Reset all jobs to queued status")
    parser.add_argument("--user-id", type=int, default=1)
    args = parser.parse_args()

    from database.connection import init_db
    init_db()

    if args.status:
        print_status_table()
        return

    if args.reset:
        reset_jobs()
        print_status_table()
        return

    # ── Seed ────────────────────────────────────────────────────────────
    print("\n[Demo] Seeding candidate profile and job queue...")
    from database.seed import seed_demo
    seed_demo()

    # Generate resume PDF if it doesn't exist
    import os
    resume_path = "assets/resumes/alex_chen_resume.pdf"
    if not os.path.exists(resume_path):
        print("[Demo] Generating resume PDF...")
        from assets.resumes.generate_resume import generate_alex_chen_resume
        generate_alex_chen_resume(resume_path)
    else:
        print(f"[Demo] Resume PDF already exists: {resume_path}")

    if args.seed_only:
        print("\n[Demo] Seed complete.")
        print("[Demo] Run  python demo.py          to start the pipeline.")
        print("[Demo] Run  python demo.py --status  to check job statuses.")
        print_status_table()
        return

    # ── Run pipeline ─────────────────────────────────────────────────────
    print("\n[Demo] Launching pipeline...\n")
    from main import run
    asyncio.run(run(user_id=args.user_id))

    # ── Final status ─────────────────────────────────────────────────────
    print("[Demo] Run complete. Final job statuses:")
    print_status_table()

    # Print backlog hint if any
    from database.connection import get_session_factory
    from database.models import Job, JobStatus
    from sqlalchemy import select

    with get_session_factory()() as session:
        backlog = session.execute(
            select(Job).where(Job.status == JobStatus.BACKLOG)
        ).scalars().all()

    if backlog:
        print(f"[Demo] {len(backlog)} job(s) in backlog.")
        print("[Demo] Add missing answers to custom_answers then run:")
        print("       python demo.py --reset && python demo.py\n")


if __name__ == "__main__":
    main()
