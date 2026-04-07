"""
agents/nodes/resume_tailor.py — Tailor the candidate resume to the job description.
Full implementation in Commit 6.
"""
from __future__ import annotations

from agents.state import AgentState


async def tailor_resume_node(state: AgentState) -> dict:
    """STUB — replaced in Commit 6."""
    print(f"  [tailor_resume] tailoring for {state.get('job_title')}")
    return {
        "tailored_resume": "STUB: tailored resume text will be generated here.",
    }
