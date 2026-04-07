"""
agents/nodes/form_filler.py — Navigate and fill the application form.
Full implementation in Commit 8.
"""
from __future__ import annotations

from agents.state import AgentState


async def browser_init_node(state: AgentState) -> dict:
    """STUB — replaced in Commit 7."""
    print(f"  [browser_init] opening browser")
    return {"browser_ready": True}


async def sign_in_node(state: AgentState) -> dict:
    """STUB — replaced in Commit 7."""
    print(f"  [sign_in] signing in to {state.get('ats_platform')}")
    return {}


async def fill_form_node(state: AgentState) -> dict:
    """STUB — replaced in Commit 8."""
    print(f"  [fill_form] filling form fields")
    return {
        "resolved_fields": [],
        "pending_hitl_field": None,
    }


async def submit_node(state: AgentState) -> dict:
    """STUB — replaced in Commit 8."""
    print(f"  [submit] submitting application")
    return {"status": "submitted"}
