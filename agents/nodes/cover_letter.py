"""
agents/nodes/cover_letter.py — Generate a tailored cover letter for the job.

Uses Groq LLM via langchain-groq. Expects user_profile already in state
(loaded by tailor_resume_node). Produces a 3-paragraph cover letter:
  1. Hook — specific role + genuine company enthusiasm
  2. Body — 2 strongest matching experiences with concrete impact
  3. Close — forward-looking, confident, concise
"""
from __future__ import annotations

import os

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage

from agents.state import AgentState


def _get_llm() -> ChatGroq:
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.5,   # slightly higher for natural writing
        max_tokens=1024,
    )


async def cover_letter_node(state: AgentState) -> dict:
    """
    Generate a cover letter using the tailored resume context and job description.
    """
    profile = state.get("user_profile") or {}
    tailored_resume = state.get("tailored_resume") or ""
    job_title = state.get("job_title") or "Software Engineer"
    job_company = state.get("job_company") or "your company"
    job_description = state.get("job_description") or ""

    full_name = profile.get("full_name", "Hrithika Pal")
    email = profile.get("email", "")
    phone = profile.get("phone", "")
    location = profile.get("location", "")

    print(f"  [cover_letter] generating for {job_title} at {job_company}")

    system_prompt = """You are a professional cover letter writer for software engineers.
Write a concise, genuine cover letter — not generic, not flattery-heavy.

Structure (3 paragraphs only):
1. Opening: name the specific role and company, state one concrete reason you're excited about this company
2. Body: highlight exactly 2 relevant experiences with specific metrics or outcomes that match the job
3. Close: express availability, reference culture/mission fit in one sentence, end with confidence

Rules:
- 250–320 words total
- No clichés: avoid "I am writing to express", "passion for", "team player", "fast learner"
- Use the candidate's actual experience — nothing fabricated
- Output ONLY the cover letter body text (no subject line, no "Dear Hiring Manager" header)
- End with a simple sign-off: "Best,\\n[Name]"
"""

    human_message = f"""CANDIDATE: {full_name}
ROLE: {job_title} at {job_company}

TAILORED RESUME:
{tailored_resume[:2000]}

JOB DESCRIPTION:
{job_description[:2000]}

Write the cover letter now."""

    try:
        llm = _get_llm()
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_message),
        ])
        cover_letter = response.content
        print(f"  [cover_letter] generated {len(cover_letter)} chars")
    except Exception as exc:
        print(f"  [cover_letter] LLM call failed: {exc}")
        # Minimal fallback so pipeline can continue
        cover_letter = (
            f"I am excited to apply for the {job_title} role at {job_company}. "
            f"With my background in software engineering, I am confident I can "
            f"contribute meaningfully to your team.\n\nBest,\n{full_name}"
        )

    return {"cover_letter": cover_letter}
