"""
agents/nodes/resume_tailor.py — Tailor the candidate resume to the job description.

Uses Groq LLM via langchain-groq. Loads the user profile from DB if not
already in state. Returns a plain-text tailored resume optimised for ATS
keyword matching — no fabrication, just intelligent reordering and emphasis.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from agents.state import AgentState

# ---------------------------------------------------------------------------
# LLM setup
# ---------------------------------------------------------------------------

def _get_llm() -> ChatGroq:
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.3,   # low temp for consistent, structured output
        max_tokens=4096,
    )


# ---------------------------------------------------------------------------
# Profile helpers
# ---------------------------------------------------------------------------

def _load_profile(user_id: int) -> dict:
    """Load full candidate profile from DB."""
    from database.connection import get_session
    from database.models import User
    from sqlalchemy.orm import selectinload
    from sqlalchemy import select

    with get_session() as session:
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
            raise ValueError(f"User {user_id} not found in database")
        return user.to_dict()


def _format_profile_for_prompt(profile: dict) -> str:
    """Render the candidate profile as a readable text block for the LLM."""
    lines = [
        f"Name: {profile['full_name']}",
        f"Location: {profile['location']}",
        f"Email: {profile['email']}",
        "",
        "PROFESSIONAL SUMMARY",
        profile["summary"],
        "",
        "WORK EXPERIENCE",
    ]

    for exp in profile["work_experiences"]:
        end = exp["end_date"] or "Present"
        lines.append(f"\n{exp['title']} — {exp['company']} ({exp['start_date']} to {end})")
        if exp.get("location"):
            lines.append(f"Location: {exp['location']}")
        lines.append(exp["description"])

    lines.append("\nEDUCATION")
    for edu in profile["educations"]:
        gpa_str = f", GPA {edu['gpa']}" if edu.get("gpa") else ""
        lines.append(
            f"{edu['degree']} in {edu['field_of_study']} — {edu['institution']} "
            f"({edu['start_date']} to {edu.get('end_date', 'Present')}{gpa_str})"
        )

    lines.append("\nSKILLS")
    by_category: dict = {}
    for skill in profile["skills"]:
        cat = skill["category"].replace("_", " ").title()
        by_category.setdefault(cat, []).append(skill["name"])
    for cat, names in by_category.items():
        lines.append(f"{cat}: {', '.join(names)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

async def tailor_resume_node(state: AgentState) -> dict:
    """
    Tailor the base resume to the job description using the LLM.
    Loads profile from DB if not already in state.
    """
    # Load profile if not already in state
    profile = state.get("user_profile")
    if not profile:
        print(f"  [tailor_resume] loading profile for user {state['user_id']}")
        profile = _load_profile(state["user_id"])

    job_title = state.get("job_title") or "Software Engineer"
    job_company = state.get("job_company") or "the company"
    job_description = state.get("job_description") or ""

    print(f"  [tailor_resume] tailoring for {job_title} at {job_company}")

    profile_text = _format_profile_for_prompt(profile)

    system_prompt = """You are an expert technical resume writer specialising in ATS optimisation.
Your task is to tailor a software engineer's resume to a specific job description.

Rules:
- Reorder bullet points within each role to surface the most relevant skills first
- Naturally incorporate keywords from the job description where they match real experience
- Do NOT fabricate experience, skills, or achievements
- Keep all dates, companies, titles, and metrics exactly as provided
- Output ONLY the tailored resume as plain text — no commentary, no markdown headers with #
- Use clear section headers in UPPERCASE (SUMMARY, EXPERIENCE, EDUCATION, SKILLS)
- Keep the resume to a single page equivalent (~600 words max)"""

    human_message = f"""CANDIDATE PROFILE:
{profile_text}

JOB DESCRIPTION:
{job_description[:3000]}

Please tailor the resume above for this {job_title} role at {job_company}.
Focus on matching the technical stack, responsibilities, and keywords in the job description."""

    try:
        llm = _get_llm()
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_message),
        ])
        tailored = response.content
        print(f"  [tailor_resume] generated {len(tailored)} chars")
    except Exception as exc:
        print(f"  [tailor_resume] LLM call failed: {exc}")
        # Fall back to the raw profile text so the pipeline can continue
        tailored = profile_text

    # Save as PDF so Workday can autofill from it
    tailored_pdf_path = _save_tailored_pdf(tailored, job_company, job_title, profile)

    return {
        "tailored_resume": tailored,
        "tailored_resume_path": tailored_pdf_path,
        "user_profile": profile,   # cache in state for cover_letter node
    }


# ---------------------------------------------------------------------------
# PDF generation
# ---------------------------------------------------------------------------

def _save_tailored_pdf(
    text: str,
    company: str,
    title: str,
    profile: dict,
) -> Optional[str]:
    """
    Render the plain-text tailored resume as a clean PDF using reportlab.
    Returns the output path, or None if reportlab is not installed.
    """
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib import colors
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.units import inch
        from reportlab.lib.enums import TA_LEFT, TA_CENTER
    except ImportError:
        print("  [tailor_resume] reportlab not installed — skipping PDF generation")
        return None

    # Safe filename: "hrithika_pal_stripe_software_engineer.pdf"
    safe_company = re.sub(r"[^\w]", "_", (company or "company").lower())[:20]
    safe_title   = re.sub(r"[^\w]", "_", (title   or "role").lower())[:30]
    out_dir = Path("assets/resumes/tailored")
    out_dir.mkdir(parents=True, exist_ok=True)
    output_path = str(out_dir / f"hrithika_pal_{safe_company}_{safe_title}.pdf")

    doc = SimpleDocTemplate(
        output_path,
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )

    name_style = ParagraphStyle(
        "Name", fontSize=18, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1a1a2e"), alignment=TA_CENTER,
        spaceAfter=4, leading=22,
    )
    contact_style = ParagraphStyle(
        "Contact", fontSize=9, fontName="Helvetica",
        textColor=colors.HexColor("#444444"), alignment=TA_CENTER, spaceAfter=6,
    )
    section_style = ParagraphStyle(
        "Section", fontSize=11, fontName="Helvetica-Bold",
        textColor=colors.HexColor("#1a1a2e"), spaceBefore=8, spaceAfter=2,
    )
    body_style = ParagraphStyle(
        "Body", fontSize=9, fontName="Helvetica",
        textColor=colors.black, spaceAfter=2, leading=13,
    )

    story = []

    # Header from profile
    name    = profile.get("full_name", "Hrithika Pal")
    email   = profile.get("email", "hrithikapal9@gmail.com")
    phone   = profile.get("phone", "+1 (415) 555-0192")
    loc     = profile.get("location", "San Francisco, CA")
    github  = (profile.get("github_url") or "").replace("https://", "")
    linkedin = (profile.get("linkedin_url") or "").replace("https://", "")

    story.append(Paragraph(name, name_style))
    story.append(Paragraph(
        f"{loc}  •  {phone}  •  {email}  •  {linkedin}  •  {github}",
        contact_style,
    ))

    # Body — render the LLM-generated text line by line
    SECTION_KEYWORDS = {"SUMMARY", "EXPERIENCE", "EDUCATION", "SKILLS",
                        "WORK EXPERIENCE", "PROJECTS", "CERTIFICATIONS"}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            story.append(Spacer(1, 3))
            continue

        upper = line.upper().rstrip(":")
        if upper in SECTION_KEYWORDS:
            story.append(Paragraph(upper, section_style))
        elif line.startswith("•") or line.startswith("-"):
            # Escape XML special chars for reportlab
            safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            story.append(Paragraph(safe, body_style))
        else:
            safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            story.append(Paragraph(safe, body_style))

    try:
        doc.build(story)
    except Exception as exc:
        print(f"  [tailor_resume] PDF build failed: {exc}")
        return None

    print(f"  [tailor_resume] saved tailored PDF: {output_path}")
    return output_path
