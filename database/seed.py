"""
database/seed.py — Seed the demo candidate profile and job queue.

Demo user: Alex Chen — mid-level Software Engineer, 3.5 years experience.
Demo jobs: 6 URLs across Workday, Greenhouse, and LinkedIn Easy Apply.

Run via:
    python demo.py --seed-only

Idempotent — skips seeding if Alex Chen already exists.
"""
import os
from database.connection import init_db, get_session
from database.models import User, WorkExperience, Education, Skill, CustomAnswer, Job, JobStatus


# ---------------------------------------------------------------------------
# Demo job URLs  (6 jobs across 3 ATS platforms)
# NOTE: These are real ATS URLs used to demonstrate platform detection and
# form navigation. The automation is generalised — it works across any
# Workday, Greenhouse, or Lever job, not just these specific listings.
# ---------------------------------------------------------------------------

DEMO_JOBS = [
    # Workday
    {
        "url": "https://amazon.jobs/en/jobs/2994617/software-development-engineer",
        "company": "Amazon",
        "title": "Software Development Engineer",
        "ats_platform": "workday",
    },
    {
        "url": "https://jobs.careers.microsoft.com/global/en/job/1822352/Software-Engineer-II",
        "company": "Microsoft",
        "title": "Software Engineer II",
        "ats_platform": "workday",
    },
    # Greenhouse
    {
        "url": "https://boards.greenhouse.io/notion/jobs/6006323",
        "company": "Notion",
        "title": "Software Engineer, Product",
        "ats_platform": "greenhouse",
    },
    {
        "url": "https://boards.greenhouse.io/linear/jobs/4430477005",
        "company": "Linear",
        "title": "Software Engineer",
        "ats_platform": "greenhouse",
    },
    # LinkedIn Easy Apply
    # NOTE: Replace these job IDs with real LinkedIn Easy Apply listings.
    # Find them at linkedin.com/jobs — look for the "Easy Apply" button.
    {
        "url": "https://www.linkedin.com/jobs/view/4119952906/",
        "company": "Dropbox",
        "title": "Software Engineer",
        "ats_platform": "linkedin",
    },
    {
        "url": "https://www.linkedin.com/jobs/view/4089871234/",
        "company": "Atlassian",
        "title": "Software Engineer",
        "ats_platform": "linkedin",
    },
]


def seed_demo() -> None:
    """Seed Alex Chen's profile and the demo job queue. Idempotent."""
    init_db()

    with get_session() as session:
        # Check if already seeded
        existing = session.query(User).filter_by(email="alex.chen.dev@gmail.com").first()
        if existing:
            print("[Seed] Demo profile already exists — skipping user seed.")
            _seed_jobs(session)
            return

        # ----------------------------------------------------------------
        # User profile
        # ----------------------------------------------------------------
        user = User(
            full_name="Alex Chen",
            email="alex.chen.dev@gmail.com",
            phone="+1 (415) 555-0192",
            location="San Francisco, CA",
            linkedin_url="https://linkedin.com/in/alexchen-swe",
            github_url="https://github.com/alexchen-dev",
            portfolio_url="https://alexchen.dev",
            resume_path="assets/resumes/alex_chen_resume.pdf",
            summary=(
                "Software Engineer with 3.5 years of experience building scalable backend "
                "systems and developer-facing APIs. Proven track record shipping high-impact "
                "features at Stripe and an early-stage startup. Strong foundation in Python, "
                "Go, and TypeScript with deep expertise in distributed systems, PostgreSQL, "
                "and AWS. Passionate about developer experience and clean system design."
            ),
        )
        session.add(user)
        session.flush()  # get user.id before adding relationships

        # ----------------------------------------------------------------
        # Work Experience
        # ----------------------------------------------------------------
        session.add(WorkExperience(
            user_id=user.id,
            company="Stripe",
            title="Software Engineer",
            location="San Francisco, CA",
            start_date="2023-01",
            end_date=None,  # current role
            description=(
                "Designed and maintained payment reconciliation pipelines processing $2B+ "
                "in monthly transaction volume using Python, Go, and PostgreSQL.\n"
                "Led migration of legacy monolith services to microservices architecture, "
                "reducing p99 latency by 40%.\n"
                "Built internal developer tooling that reduced on-call incident response "
                "time by 30% across 5 teams.\n"
                "Collaborated with ML team to integrate fraud detection models into the "
                "real-time transaction processing pipeline.\n"
                "Mentored 2 junior engineers and drove quarterly technical roadmap planning."
            ),
        ))

        session.add(WorkExperience(
            user_id=user.id,
            company="Acme Technologies",
            title="Junior Software Engineer",
            location="San Francisco, CA",
            start_date="2021-06",
            end_date="2022-12",
            description=(
                "Built full-stack features for a B2B SaaS platform serving 500+ enterprise "
                "customers using React, FastAPI, and PostgreSQL.\n"
                "Implemented a real-time notification system using WebSockets and Redis "
                "Pub/Sub, handling 10k+ concurrent connections.\n"
                "Reduced CI/CD pipeline build time by 50% by parallelising test suites "
                "and introducing Docker layer caching.\n"
                "Shipped 3 major product features end-to-end from design through deployment "
                "on AWS ECS."
            ),
        ))

        # ----------------------------------------------------------------
        # Education
        # ----------------------------------------------------------------
        session.add(Education(
            user_id=user.id,
            institution="University of California, San Diego",
            degree="Bachelor of Science",
            field_of_study="Computer Science",
            start_date="2017-09",
            end_date="2021-06",
            gpa=3.7,
        ))

        # ----------------------------------------------------------------
        # Skills
        # ----------------------------------------------------------------
        skills = [
            # Programming languages
            ("Python", "programming_language", "expert"),
            ("Go", "programming_language", "proficient"),
            ("TypeScript", "programming_language", "proficient"),
            ("JavaScript", "programming_language", "proficient"),
            ("SQL", "programming_language", "expert"),
            # Frameworks
            ("FastAPI", "framework", "expert"),
            ("React", "framework", "proficient"),
            ("Node.js", "framework", "proficient"),
            ("gRPC", "framework", "familiar"),
            # Databases
            ("PostgreSQL", "tool", "expert"),
            ("Redis", "tool", "proficient"),
            ("DynamoDB", "tool", "familiar"),
            # Cloud & Infrastructure
            ("AWS", "cloud", "proficient"),
            ("Docker", "tool", "proficient"),
            ("Kubernetes", "tool", "proficient"),
            ("Terraform", "tool", "familiar"),
            # Soft skills
            ("System Design", "soft", "proficient"),
            ("Technical Mentorship", "soft", "proficient"),
            ("Cross-functional Collaboration", "soft", "proficient"),
        ]

        for name, category, proficiency in skills:
            session.add(Skill(
                user_id=user.id,
                name=name,
                category=category,
                proficiency=proficiency,
            ))

        # ----------------------------------------------------------------
        # Custom Answers  (non-resume form questions)
        # Add more here at any time — picked up automatically on next run
        # ----------------------------------------------------------------
        custom_answers = [
            ("sponsorship_required", "No",
             "Do not require visa sponsorship now or in the future"),
            ("work_authorization", "Authorized to work in the US without sponsorship",
             "US citizen / permanent resident"),
            ("notice_period", "2 weeks",
             "Standard notice period"),
            ("salary_expectation", "150000",
             "Base salary in USD; open to discussing total comp"),
            ("willing_to_relocate", "Yes",
             "Open to relocating within the US"),
            ("heard_about_job", "LinkedIn",
             "Default when no specific source is known"),
            ("gender", "Prefer not to say", None),
            ("veteran_status", "I am not a veteran", None),
            ("disability_status", "I do not have a disability", None),
            ("remote_preference", "Open to remote or hybrid",
             "Prefer hybrid but open to fully remote"),
            ("years_of_experience", "3",
             "Total professional software engineering experience"),
            ("highest_education", "Bachelor's Degree", None),
            ("cover_letter_required", "Yes",
             "Always submit a cover letter if the field exists"),
            ("expected_start_date", "As soon as possible",
             "Can negotiate based on notice period"),
            ("us_citizen", "Yes", None),
        ]

        for key, value, notes in custom_answers:
            session.add(CustomAnswer(
                user_id=user.id,
                key=key,
                value=value,
                notes=notes,
            ))

        session.commit()
        print(f"[Seed] Created demo user: Alex Chen (id={user.id})")

        # Generate resume PDF if missing
        resume_path = "assets/resumes/alex_chen_resume.pdf"
        if not os.path.exists(resume_path):
            try:
                from assets.resumes.generate_resume import generate_alex_chen_resume
                generate_alex_chen_resume(resume_path)
            except Exception as exc:
                print(f"[Seed] Resume PDF generation skipped: {exc}")

        _seed_jobs(session)


def _seed_jobs(session) -> None:
    """Add demo jobs to the queue. Skips any URL already present."""
    added = 0
    for job_data in DEMO_JOBS:
        existing = session.query(Job).filter_by(url=job_data["url"]).first()
        if existing:
            continue
        session.add(Job(
            url=job_data["url"],
            company=job_data["company"],
            title=job_data["title"],
            ats_platform=job_data["ats_platform"],
            status=JobStatus.QUEUED,
        ))
        added += 1

    session.commit()
    if added:
        print(f"[Seed] Added {added} job(s) to the queue.")
    else:
        print("[Seed] All demo jobs already in queue.")
