"""
agents/nodes/hitl.py — Human-in-the-loop: 30s terminal prompt for ambiguous fields.
Full implementation in Commit 9.
"""
from __future__ import annotations

from agents.state import AgentState


async def hitl_node(state: AgentState) -> dict:
    """STUB — replaced in Commit 9."""
    print(f"  [hitl] would prompt user for: {state.get('pending_hitl_field')}")
    return {"status": "backlog"}


async def record_result_node(state: AgentState) -> dict:
    """Persist final job status to the database."""
    from database.connection import get_session
    from database.models import Job

    job_id = state["job_id"]
    status = state.get("status", "failed")

    with get_session() as session:
        job = session.get(Job, job_id)
        if job:
            job.status = status
            job.failure_reason = state.get("error")
            if state.get("unanswered_fields"):
                job.unanswered_fields = state["unanswered_fields"]
            session.commit()

    print(f"  [record_result] job {job_id} → {status}")
    return {}
