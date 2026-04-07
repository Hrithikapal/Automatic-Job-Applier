"""
agents/nodes/job_scraper.py — Scrape the job description from the job URL.
Full implementation in Commit 5.
"""
from __future__ import annotations

from agents.state import AgentState


async def scrape_jd_node(state: AgentState) -> dict:
    """STUB — replaced in Commit 5."""
    print(f"  [scrape_jd] {state['job_url']}")
    return {
        "job_description": "STUB: job description will be scraped here.",
        "job_title": state.get("job_title") or "Software Engineer",
        "job_company": state.get("job_company") or "Unknown Company",
    }
