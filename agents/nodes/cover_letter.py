"""
agents/nodes/cover_letter.py — Generate a cover letter for the job.
Full implementation in Commit 6.
"""
from __future__ import annotations

from agents.state import AgentState


async def cover_letter_node(state: AgentState) -> dict:
    """STUB — replaced in Commit 6."""
    print(f"  [cover_letter] generating for {state.get('job_company')}")
    return {
        "cover_letter": "STUB: cover letter will be generated here.",
    }
