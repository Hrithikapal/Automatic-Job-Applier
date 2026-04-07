"""
agents/state.py — AgentState is the single shared contract between all nodes.

Every node receives the full state and returns a partial dict to merge.
LangGraph handles the merging automatically.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class FieldResolutionResult(TypedDict):
    field_label: str
    field_type: str         # text | select | radio | checkbox | textarea | file
    field_locator: str      # Playwright-compatible selector
    resolved_value: Optional[str]
    resolution_source: str  # profile | custom_answer | llm | hitl | unanswered
    confidence: float       # 0.0 – 1.0
    context: str            # surrounding form context for debugging


class AgentState(TypedDict):
    # ── Job being processed ──────────────────────────────────────────────
    job_id: int
    job_url: str
    job_title: Optional[str]
    job_company: Optional[str]
    job_description: Optional[str]
    ats_platform: Optional[str]     # workday | greenhouse | lever | linkedin | ashby

    # ── Candidate profile (loaded once, passed through all nodes) ────────
    user_id: int
    user_profile: Optional[Dict]    # serialised User.to_dict()

    # ── Generated artefacts ──────────────────────────────────────────────
    tailored_resume: Optional[str]  # plain-text resume tailored to this JD
    cover_letter: Optional[str]

    # ── Browser session state ────────────────────────────────────────────
    browser_ready: bool
    current_page_url: Optional[str]
    form_fields: Optional[List[Dict]]               # raw fields from DOM scan
    resolved_fields: Optional[List[FieldResolutionResult]]

    # ── HITL ─────────────────────────────────────────────────────────────
    pending_hitl_field: Optional[FieldResolutionResult]  # field awaiting input

    # ── Execution control ────────────────────────────────────────────────
    status: str             # mirrors Job.status
    error: Optional[str]
    unanswered_fields: List[Dict]   # accumulates across HITL timeouts
    retry_count: int

    # ── Metadata ─────────────────────────────────────────────────────────
    started_at: Optional[str]
    messages: List[Any]     # LangChain message history for LLM calls
