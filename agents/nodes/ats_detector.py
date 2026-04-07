"""
agents/nodes/ats_detector.py — Detect the ATS platform from URL and DOM fingerprint.
Full implementation in Commit 5.
"""
from __future__ import annotations

from agents.state import AgentState


async def ats_detect_node(state: AgentState) -> dict:
    """STUB — replaced in Commit 5."""
    platform = state.get("ats_platform") or "unknown"
    print(f"  [ats_detect] platform={platform}")
    return {"ats_platform": platform}
