"""
setup_answers.py — Interactive setup for custom answer pairs.

Run this once before your first job run, and any time you want to update
your answers. Every answer saved here is automatically picked up on every
future run — no code changes needed.

HITL during runs also saves answers here automatically, so the list grows
over time as new questions are encountered.

Usage:
    python setup_answers.py            # walk through all questions
    python setup_answers.py --show     # print current answers and exit
    python setup_answers.py --add      # add a single custom answer manually
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from dotenv import load_dotenv
load_dotenv()


# ---------------------------------------------------------------------------
# Common questions asked by job application forms
# Format: (key, human-readable question, hint)
# ---------------------------------------------------------------------------

COMMON_QUESTIONS = [
    # Work authorisation
    (
        "work_authorization",
        "Are you legally authorized to work in the US?",
        "e.g. Yes / No / Authorized with OPT / Authorized with H1-B",
    ),
    (
        "sponsorship_required",
        "Do you require visa sponsorship now or in the future?",
        "e.g. No / Yes / Not currently but may in future",
    ),
    (
        "us_citizen",
        "Are you a US citizen or permanent resident?",
        "e.g. Yes / No",
    ),

    # Job terms
    (
        "notice_period",
        "What is your notice period / when can you start?",
        "e.g. 2 weeks / Immediately / 30 days / As soon as possible",
    ),
    (
        "salary_expectation",
        "What is your salary expectation (annual, USD)?",
        "e.g. 150000  (numbers only or a range like 140000-160000)",
    ),
    (
        "expected_start_date",
        "What is your expected start date?",
        "e.g. As soon as possible / 2 weeks notice / June 2025",
    ),

    # Work style
    (
        "willing_to_relocate",
        "Are you willing to relocate?",
        "e.g. Yes / No / Open to discussing",
    ),
    (
        "remote_preference",
        "What is your remote work preference?",
        "e.g. Remote / Hybrid / On-site / Open to all",
    ),
    (
        "willing_to_travel",
        "Are you willing to travel for work?",
        "e.g. Yes up to 20% / No / Occasionally",
    ),

    # Experience
    (
        "years_of_experience",
        "How many years of professional software engineering experience do you have?",
        "e.g. 3 / 5 / 7+",
    ),
    (
        "highest_education",
        "What is your highest level of education completed?",
        "e.g. Bachelor's Degree / Master's Degree / PhD / Associate's Degree",
    ),

    # How heard
    (
        "heard_about_job",
        "How did you hear about this job? (default answer when not known)",
        "e.g. LinkedIn / Company website / Indeed / Referral",
    ),

    # Voluntary / demographic (all optional — press Enter to skip)
    (
        "gender",
        "Gender (voluntary — press Enter to skip)",
        "e.g. Female / Male / Non-binary / Prefer not to say",
    ),
    (
        "hispanic_ethnicity",
        "Are you Hispanic or Latino? (voluntary — press Enter to skip)",
        "e.g. No, not Hispanic or Latino / Yes / Prefer not to say",
    ),
    (
        "race_ethnicity",
        "Race / ethnicity (voluntary — press Enter to skip)",
        "e.g. Asian / White / Black or African American / Prefer not to say",
    ),
    (
        "veteran_status",
        "Veteran status (voluntary — press Enter to skip)",
        "e.g. I am not a veteran / Protected veteran / Prefer not to disclose",
    ),
    (
        "disability_status",
        "Disability status (voluntary — press Enter to skip)",
        "e.g. I do not have a disability / I have a disability / Prefer not to say",
    ),
]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_user_id() -> int:
    from database.connection import get_session
    from database.models import User
    with get_session() as session:
        user = session.query(User).first()
        if not user:
            print("  [setup] No user profile found. Run  python demo.py --seed-only  first.")
            sys.exit(1)
        return user.id


def _load_existing(user_id: int) -> dict[str, str]:
    """Return current custom answers as {key: value}."""
    from database.connection import get_session
    from database.models import CustomAnswer
    with get_session() as session:
        rows = session.query(CustomAnswer).filter_by(user_id=user_id).all()
        return {row.key: row.value for row in rows}


def _save_answer(user_id: int, key: str, value: str) -> None:
    """Upsert a single custom answer."""
    from database.connection import get_session
    from database.models import CustomAnswer
    from datetime import datetime
    with get_session() as session:
        existing = session.query(CustomAnswer).filter_by(user_id=user_id, key=key).first()
        if existing:
            existing.value = value
            existing.updated_at = datetime.utcnow()
        else:
            session.add(CustomAnswer(
                user_id=user_id,
                key=key,
                value=value,
                notes="Set via setup_answers.py",
            ))
        session.commit()


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _print_banner() -> None:
    print()
    print("=" * 65)
    print("  AI Job Applier — Custom Answer Setup")
    print("=" * 65)
    print("  Answers saved here are used automatically on every job run.")
    print("  Press Enter to keep the existing value.  Ctrl+C to quit.")
    print("=" * 65)
    print()


def _print_table(existing: dict[str, str]) -> None:
    if not existing:
        print("  No custom answers saved yet.\n")
        return
    print()
    print(f"  {'KEY':<35} {'VALUE'}")
    print(f"  {'─' * 34} {'─' * 30}")
    for key, value in sorted(existing.items()):
        print(f"  {key:<35} {value}")
    print()


# ---------------------------------------------------------------------------
# Interactive walkthrough
# ---------------------------------------------------------------------------

def run_setup(user_id: int) -> None:
    existing = _load_existing(user_id)
    _print_banner()

    saved_count = 0

    for key, question, hint in COMMON_QUESTIONS:
        current = existing.get(key)

        # Build the prompt line
        if current:
            prompt = f"  {question}\n  [{current}]: "
        else:
            prompt = f"  {question}\n  Hint: {hint}\n  Answer: "

        try:
            raw = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n  Setup interrupted. Answers saved so far are kept.\n")
            break

        print()

        if not raw:
            if current:
                # Keep existing — nothing to do
                pass
            # else: optional field left blank — skip
            continue

        _save_answer(user_id, key, raw)
        existing[key] = raw
        saved_count += 1

    print(f"  Done! {saved_count} answer(s) saved.")
    print(f"  These will be used automatically on every future run.\n")


# ---------------------------------------------------------------------------
# --add mode: manually add an arbitrary key-value pair
# ---------------------------------------------------------------------------

def run_add(user_id: int) -> None:
    existing = _load_existing(user_id)
    print()
    print("  Add a custom answer. The key should be lowercase_underscore.")
    print("  Examples:  notice_period   salary_expectation   citizenship")
    print()

    try:
        key = input("  Key   : ").strip().lower().replace(" ", "_")
        if not key:
            print("  Empty key — nothing saved.")
            return
        current = existing.get(key)
        if current:
            print(f"  Current value: '{current}'")
        value = input("  Value : ").strip()
        if not value:
            print("  Empty value — nothing saved.")
            return
    except (EOFError, KeyboardInterrupt):
        print("\n  Cancelled.")
        return

    _save_answer(user_id, key, value)
    print(f"\n  Saved: {key} = '{value}'\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    from database.connection import init_db
    init_db()

    parser = argparse.ArgumentParser(
        description="Set up custom answers for the AI Job Applier"
    )
    parser.add_argument("--show", action="store_true",
                        help="Print all current answers and exit")
    parser.add_argument("--add", action="store_true",
                        help="Add a single custom key-value answer")
    args = parser.parse_args()

    user_id = _get_user_id()

    if args.show:
        existing = _load_existing(user_id)
        print("\n  Current custom answers:")
        _print_table(existing)
        return

    if args.add:
        run_add(user_id)
        return

    run_setup(user_id)


if __name__ == "__main__":
    main()
