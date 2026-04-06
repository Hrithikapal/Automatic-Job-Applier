"""
demo.py — Seed the demo profile and run the full pipeline.

Usage:
    python demo.py              # seed + run
    python demo.py --seed-only  # only seed, don't run
    python demo.py --status     # print job status table
"""
import argparse
import asyncio


def print_status_table() -> None:
    from database.connection import init_db, get_session_factory
    from database.models import Job
    from sqlalchemy import select

    init_db()
    with get_session_factory()() as session:
        jobs = session.execute(select(Job).order_by(Job.id)).scalars().all()
        if not jobs:
            print("No jobs in queue.")
            return

        print(f"\n{'ID':<4} {'Company':<20} {'Title':<35} {'ATS':<12} {'Status':<12}")
        print("─" * 90)
        for job in jobs:
            company = (job.company or "—")[:19]
            title = (job.title or "—")[:34]
            ats = (job.ats_platform or "—")[:11]
            print(f"{job.id:<4} {company:<20} {title:<35} {ats:<12} {job.status:<12}")
        print()


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Job Application Agent — Demo")
    parser.add_argument("--seed-only", action="store_true", help="Seed DB and exit")
    parser.add_argument("--status", action="store_true", help="Print job status table")
    parser.add_argument("--user-id", type=int, default=1)
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    from database.connection import init_db
    init_db()

    if args.status:
        print_status_table()
        return

    from database.seed import seed_demo
    seed_demo()

    if args.seed_only:
        print("\n[Demo] Seed complete. Run `python demo.py` to start the pipeline.")
        print_status_table()
        return

    print("\n[Demo] Starting pipeline...")
    from main import run
    asyncio.run(run(user_id=args.user_id))

    print("\n[Demo] Final status:")
    print_status_table()


if __name__ == "__main__":
    main()
