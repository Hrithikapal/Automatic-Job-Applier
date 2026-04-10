"""
database/seed.py — Seed the demo candidate profile and job queue.

Demo user: Hrithika Pal — mid-level Software Engineer, 3.5 years experience.
Demo jobs: 6 real URLs across Workday, Greenhouse, and Lever.

Run via:
    python demo.py --seed-only

Idempotent — skips seeding if Hrithika Pal already exists.
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
        "url": "https://workday.wd5.myworkdayjobs.com/en-US/Workday/details/Software-Development-Engineer_JR-0105664?Location_Country=c4f78be1a8f14da0ab49ce1162348a5e",
        "company": "Workday",
        "title": "Software Development Engineer",
        "ats_platform": "workday",
    },
    {
        "url": "https://workday.wd5.myworkdayjobs.com/en-US/Workday/details/Principal-Software-Development-Engineer_JR-0105659?Location_Country=c4f78be1a8f14da0ab49ce1162348a5e",
        "company": "Workday",
        "title": "Principal Software Development Engineer",
        "ats_platform": "workday",
    },
    # Greenhouse
    {
        "url": "https://job-boards.greenhouse.io/postman/jobs/7687341003",
        "company": "Postman",
        "title": "Software Engineer, IAM",
        "ats_platform": "greenhouse",
    },
    {
        "url": "https://job-boards.greenhouse.io/easyship/jobs/4588340006",
        "company": "Easyship",
        "title": "Software Engineer",
        "ats_platform": "greenhouse",
    },
    # LinkedIn Easy Apply
    # NOTE: Replace job IDs with real LinkedIn Easy Apply listings.
    # Use the direct /jobs/view/<id>/ URL format (more reliable than search-results).
    # Find them at linkedin.com/jobs — look for the "Easy Apply" button.
    {
        "url": "https://www.linkedin.com/jobs/view/4386720314/",
        "company": "Emburse",
        "title": "Software Engineer III - Node.JS",
        "ats_platform": "linkedin",
    },
    {
        "url": "https://www.linkedin.com/jobs/view/4397276758/",
        "company": "Radiant Digital",
        "title": "Full Stack Engineer",
        "ats_platform": "linkedin",
    },
]


def seed_demo() -> None:
    """Seed Hrithika Pal's profile and the demo job queue. Idempotent."""
    init_db()

    with get_session() as session:
        # Check if already seeded
        existing = session.query(User).filter_by(email="hrithikapal9@gmail.com").first()
        if existing:
            print("[Seed] Demo profile already exists — skipping user seed.")
            _seed_jobs(session)
            return

        # ----------------------------------------------------------------
        # User profile
        # ----------------------------------------------------------------
        user = User(
            full_name="Hrithika Pal",
            email="hrithikapal9@gmail.com",
            phone="04155 550 192",
            location="San Francisco, CA",
            linkedin_url="https://linkedin.com/in/alexchen-swe",
            github_url="https://github.com/Hrithikapal",
            portfolio_url="https://alexchen.dev",
            resume_path="assets/resumes/hrithika_pal_resume.pdf",
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
            ("salary_expectation", "150kUSD",
             "Base salary in USD; open to discussing total comp"),
            ("willing_to_relocate", "Yes",
             "Open to relocating within the US"),
            ("heard_about_job", "LinkedIn",
             "Default when no specific source is known"),
            ("gender", "Prefer not to say", None),
            ("hispanic_ethnicity", "No, not hispanic or latino", None),
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
            ("privacy_policy", "Yes",
             "Agree to privacy policy and data processing"),
            ("data_processing", "Yes",
             "Agree to data processing for application"),
            ("terms_and_conditions", "Yes",
             "Agree to terms and conditions"),
        ]

        for key, value, notes in custom_answers:
            session.add(CustomAnswer(
                user_id=user.id,
                key=key,
                value=value,
                notes=notes,
            ))

        session.commit()
        print(f"[Seed] Created demo user: Hrithika Pal (id={user.id})")

        # Generate resume PDF if missing
        resume_path = "assets/resumes/hrithika_pal_resume.pdf"
        if not os.path.exists(resume_path):
            try:
                from assets.resumes.generate_resume import generate_hrithika_pal_resume
                generate_hrithika_pal_resume(resume_path)
            except Exception as exc:
                print(f"[Seed] Resume PDF generation skipped: {exc}")

        _seed_jobs(session)


def _seed_jobs(session, force: bool = False) -> None:
    """
    Seed DEMO_JOBS into the queue.

    force=True  — delete ALL existing jobs first, then re-insert every entry.
    force=False — skip URLs already present (default / first-time behaviour).
    """
    if force:
        deleted = session.query(Job).delete()
        session.commit()
        print(f"[Seed] Cleared {deleted} existing job(s) from the queue.")

    added = 0
    for job_data in DEMO_JOBS:
        if not force:
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
    print(f"[Seed] Added {added} job(s) to the queue.")


def reseed_jobs() -> None:
    """Delete all existing jobs and re-insert DEMO_JOBS fresh."""
    init_db()
    with get_session() as session:
        _seed_jobs(session, force=True)
