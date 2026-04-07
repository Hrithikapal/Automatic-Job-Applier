"""
agents/nodes/form_filler.py — Browser init, sign-in, form fill loop, and submit.

browser_init_node  — launches Playwright, navigates to the job URL
sign_in_node       — selects the right ATS handler and signs in
fill_form_node     — extracts fields, resolves each, fills, advances sections
submit_node        — clicks submit, closes browser
"""
from __future__ import annotations

import os
from typing import Optional

from agents.state import AgentState, FieldResolutionResult
from browser.session import BrowserSession

# Shared browser session — lives for the duration of one job run
_session: Optional[BrowserSession] = None


def _get_handler(platform: str, session: BrowserSession):
    """Return the right ATS handler for the detected platform."""
    from browser.ats.workday import WorkdayHandler
    from browser.ats.greenhouse import GreenhouseHandler
    from browser.ats.lever import LeverHandler
    from browser.ats.linkedin import LinkedInHandler

    handlers = {
        "workday":    WorkdayHandler,
        "greenhouse": GreenhouseHandler,
        "lever":      LeverHandler,
        "linkedin":   LinkedInHandler,
        # amazon/microsoft jobs redirect to Workday
        "amazon":     WorkdayHandler,
        "microsoft":  WorkdayHandler,
    }
    cls = handlers.get(platform, GreenhouseHandler)
    return cls(session)


def _get_credentials(platform: str) -> tuple[str, str]:
    """Load platform credentials from environment variables."""
    platform_map = {
        "workday":    ("WORKDAY_EMAIL",    "WORKDAY_PASSWORD"),
        "greenhouse": ("GREENHOUSE_EMAIL", "GREENHOUSE_PASSWORD"),
        "lever":      ("LEVER_EMAIL",      "LEVER_PASSWORD"),
        "linkedin":   ("LINKEDIN_EMAIL",   "LINKEDIN_PASSWORD"),
        "amazon":     ("WORKDAY_EMAIL",    "WORKDAY_PASSWORD"),
        "microsoft":  ("WORKDAY_EMAIL",    "WORKDAY_PASSWORD"),
    }
    email_key, pass_key = platform_map.get(platform, ("WORKDAY_EMAIL", "WORKDAY_PASSWORD"))
    return os.getenv(email_key, ""), os.getenv(pass_key, "")


# ---------------------------------------------------------------------------
# browser_init_node
# ---------------------------------------------------------------------------

async def browser_init_node(state: AgentState) -> dict:
    """Launch Playwright and open the job URL."""
    global _session

    print(f"  [browser_init] launching browser")
    _session = BrowserSession()
    await _session.start()

    try:
        await _session.page.goto(
            state["job_url"], wait_until="networkidle", timeout=30_000
        )
        print(f"  [browser_init] page loaded: {state['job_url']}")
    except Exception as exc:
        print(f"  [browser_init] page load failed: {exc}")
        await _session.close()
        _session = None
        return {"status": "failed", "error": f"Browser init failed: {exc}"}

    return {
        "browser_ready": True,
        "current_page_url": state["job_url"],
    }


# ---------------------------------------------------------------------------
# sign_in_node
# ---------------------------------------------------------------------------

async def sign_in_node(state: AgentState) -> dict:
    """Detect the ATS platform from DOM and sign in."""
    global _session

    if not _session or not _session.is_open:
        return {"status": "failed", "error": "Browser session not available"}

    platform = state.get("ats_platform") or "unknown"

    # Run DOM fingerprint detection now that browser is open
    from agents.nodes.ats_detector import detect_from_dom, detect_from_url
    try:
        dom_platform = await detect_from_dom(_session.page)
        if dom_platform:
            platform = dom_platform
            print(f"  [sign_in] DOM detection confirmed platform: {platform}")
    except Exception as exc:
        print(f"  [sign_in] DOM detection failed: {exc}")

    handler = _get_handler(platform, _session)
    email, password = _get_credentials(platform)

    if email and password:
        await handler.sign_in(email, password)
    else:
        print(f"  [sign_in] no credentials for {platform} — skipping sign-in")

    # Navigate to the application form
    await handler.navigate_to_apply(state["job_url"])

    return {"ats_platform": platform}


# ---------------------------------------------------------------------------
# fill_form_node
# ---------------------------------------------------------------------------

async def fill_form_node(state: AgentState) -> dict:
    """
    Main form-fill loop:
      1. Extract fields from current page/section
      2. Resolve each field through the 4-step chain
      3. Fill resolved fields
      4. If a field needs HITL, pause and return it as pending
      5. Advance to next section and repeat until no more sections
    """
    global _session

    if not _session or not _session.is_open:
        return {"status": "failed", "error": "Browser session not available"}

    platform = state.get("ats_platform", "unknown")
    handler = _get_handler(platform, _session)

    profile = state.get("user_profile") or {}
    job_description = state.get("job_description") or ""
    job_title = state.get("job_title") or "Software Engineer"
    hitl_threshold = float(os.getenv("LLM_CONFIDENCE_THRESHOLD", "0.7"))

    from agents.nodes.field_resolver import resolve_field

    resolved_fields: list = list(state.get("resolved_fields") or [])
    unanswered_fields: list = list(state.get("unanswered_fields") or [])

    # Extract fields on the current page section
    raw_fields = await handler.extract_form_fields()

    if not raw_fields:
        print(f"  [fill_form] no fields found on current section")
        return {
            "resolved_fields": resolved_fields,
            "pending_hitl_field": None,
        }

    print(f"  [fill_form] resolving {len(raw_fields)} fields")

    for field in raw_fields:
        label = field.get("label", "")
        locator = field.get("locator", "")
        field_type = field.get("field_type", "text")

        # Resolve value
        result: FieldResolutionResult = await resolve_field(
            field=field,
            profile=profile,
            job_description=job_description,
            job_title=job_title,
            hitl_threshold=hitl_threshold,
        )

        # HITL needed — pause and surface to hitl_node
        if result["resolution_source"] == "hitl":
            result["field_locator"] = locator
            print(f"  [fill_form] HITL needed for: '{label}'")
            return {
                "resolved_fields": resolved_fields,
                "pending_hitl_field": result,
                "unanswered_fields": unanswered_fields,
            }

        # Fill the field
        if result["resolved_value"] and locator:
            success = await handler.fill_field(
                locator, result["resolved_value"], field_type
            )
            if success:
                print(f"    filled '{label}' = '{result['resolved_value'][:40]}' "
                      f"[{result['resolution_source']}]")
            else:
                print(f"    failed to fill '{label}'")

        resolved_fields.append(result)

    # Try to advance to next section
    has_next = await handler.next_section()
    if has_next:
        print(f"  [fill_form] advanced to next section")
        # Return to fill_form via the graph loop (no pending HITL)
        return {
            "resolved_fields": resolved_fields,
            "pending_hitl_field": None,
            "unanswered_fields": unanswered_fields,
        }

    # No more sections — ready to submit
    print(f"  [fill_form] all sections complete")
    return {
        "resolved_fields": resolved_fields,
        "pending_hitl_field": None,
        "unanswered_fields": unanswered_fields,
    }


# ---------------------------------------------------------------------------
# submit_node
# ---------------------------------------------------------------------------

async def submit_node(state: AgentState) -> dict:
    """Submit the completed application and close the browser."""
    global _session

    if not _session or not _session.is_open:
        return {"status": "failed", "error": "Browser not available for submit"}

    platform = state.get("ats_platform", "unknown")
    handler = _get_handler(platform, _session)

    print(f"  [submit] submitting application")
    success = await handler.submit_application()

    # Update DB
    from database.connection import get_session as db_session
    from database.models import Job
    from datetime import datetime

    with db_session() as session:
        job = session.get(Job, state["job_id"])
        if job:
            job.status = "submitted" if success else "failed"
            if not success:
                job.failure_reason = "Submit button click failed"
            if state.get("tailored_resume"):
                job.tailored_resume_text = state["tailored_resume"]
            session.commit()

    await _session.close()
    _session = None

    return {"status": "submitted" if success else "failed"}
