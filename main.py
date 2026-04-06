"""
main.py — Job application processing loop.

Dequeues jobs one by one and runs each through the LangGraph pipeline.
"""
import asyncio
import argparse
import os
from dotenv import load_dotenv

load_dotenv()


async def run(user_id: int = 1) -> None:
    from database.connection import init_db, get_session_factory
    from queue.manager import JobQueueManager
    from agents.graph import build_graph

    init_db()
    session_factory = get_session_factory()
    queue = JobQueueManager(session_factory)
    graph = build_graph()

    print("[Agent] Starting job application loop...")

    processed = 0
    while True:
        job = queue.dequeue_next()
        if not job:
            print(f"[Agent] Queue empty. Processed {processed} job(s).")
            break

        print(f"\n[Agent] ── Job {job.id}: {job.url}")

        initial_state: dict = {
            "job_id": job.id,
            "job_url": job.url,
            "user_id": user_id,
            "status": "processing",
            "unanswered_fields": [],
            "retry_count": 0,
            "messages": [],
            "browser_ready": False,
            "job_title": job.title,
            "job_company": job.company,
            "job_description": None,
            "ats_platform": job.ats_platform,
            "user_profile": None,
            "tailored_resume": None,
            "cover_letter": None,
            "current_page_url": None,
            "form_fields": None,
            "resolved_fields": None,
            "pending_hitl_field": None,
            "error": None,
            "started_at": None,
        }

        try:
            result = await graph.ainvoke(initial_state)
            print(f"[Agent] Job {job.id} → {result.get('status', 'unknown')}")
        except Exception as exc:
            print(f"[Agent] Job {job.id} crashed: {exc}")
            queue.mark_failed(job.id, str(exc))

        processed += 1


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Job Application Agent")
    parser.add_argument("--user-id", type=int, default=1, help="Candidate user ID")
    args = parser.parse_args()
    asyncio.run(run(user_id=args.user_id))


if __name__ == "__main__":
    main()
