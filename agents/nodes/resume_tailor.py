"""
agents/nodes/resume_tailor.py — Tailor the candidate resume to the job description.

Uses Claude via langchain-anthropic. Loads the user profile from DB if not
already in state. Returns a plain-text tailored resume optimised for ATS
keyword matching — no fabrication, just intelligent reordering and emphasis.
"""
from __future__ import annotations

import os
from typing import Optional

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from agents.state import AgentState

# ---------------------------------------------------------------------------
# LLM setup
# ---------------------------------------------------------------------------

def _get_llm() -> ChatAnthropic:
    return ChatAnthropic(
        model="claude-opus-4-6",
        api_key=os.getenv("ANTHROPIC_API_KEY"),
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
    Tailor the base resume to the job description using Claude.
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

    return {
        "tailored_resume": tailored,
        "user_profile": profile,   # cache in state for cover_letter node
    }
