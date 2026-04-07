"""
agents/graph.py — LangGraph StateGraph definition.

Nodes are wired here. Stub implementations are replaced commit by commit.
Conditional edges handle HITL branching and error routing.
"""
from __future__ import annotations

from langgraph.graph import StateGraph, END

from agents.state import AgentState
from agents.nodes.job_scraper import scrape_jd_node
from agents.nodes.resume_tailor import tailor_resume_node
from agents.nodes.cover_letter import cover_letter_node
from agents.nodes.ats_detector import ats_detect_node
from agents.nodes.form_filler import (
    browser_init_node,
    sign_in_node,
    fill_form_node,
    submit_node,
)
from agents.nodes.hitl import hitl_node, record_result_node


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def route_after_fill(state: AgentState) -> str:
    """
    After fill_form:
      - pending HITL field  → go to hitl node
      - error               → record result (failed)
      - otherwise           → submit
    """
    if state.get("status") == "failed":
        return "error"
    if state.get("pending_hitl_field"):
        return "hitl"
    return "submit"


def route_after_hitl(state: AgentState) -> str:
    """
    After HITL:
      - user answered (status still processing) → back to fill_form
      - timeout (status = backlog)              → record result
    """
    if state.get("status") == "backlog":
        return "backlog"
    return "fill_form"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # ── Register nodes ───────────────────────────────────────────────────
    graph.add_node("scrape_jd", scrape_jd_node)
    graph.add_node("tailor_resume", tailor_resume_node)
    graph.add_node("cover_letter", cover_letter_node)
    graph.add_node("browser_init", browser_init_node)
    graph.add_node("ats_detect", ats_detect_node)
    graph.add_node("sign_in", sign_in_node)
    graph.add_node("fill_form", fill_form_node)
    graph.add_node("hitl", hitl_node)
    graph.add_node("submit", submit_node)
    graph.add_node("record_result", record_result_node)

    # ── Linear edges ─────────────────────────────────────────────────────
    graph.set_entry_point("scrape_jd")
    graph.add_edge("scrape_jd", "tailor_resume")
    graph.add_edge("tailor_resume", "cover_letter")
    graph.add_edge("cover_letter", "browser_init")
    graph.add_edge("browser_init", "ats_detect")
    graph.add_edge("ats_detect", "sign_in")
    graph.add_edge("sign_in", "fill_form")

    # ── Conditional: after fill_form ─────────────────────────────────────
    graph.add_conditional_edges(
        "fill_form",
        route_after_fill,
        {
            "hitl": "hitl",
            "submit": "submit",
            "error": "record_result",
        },
    )

    # ── Conditional: after HITL ──────────────────────────────────────────
    graph.add_conditional_edges(
        "hitl",
        route_after_hitl,
        {
            "fill_form": "fill_form",
            "backlog": "record_result",
        },
    )

    graph.add_edge("submit", "record_result")
    graph.add_edge("record_result", END)

    return graph.compile()
