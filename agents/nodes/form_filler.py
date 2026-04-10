"""
agents/nodes/form_filler.py — Browser init, sign-in, form fill loop, and submit.

browser_init_node  — launches Playwright, navigates to the job URL
sign_in_node       — selects the right ATS handler and signs in
fill_form_node     — extracts fields, resolves each, fills, advances sections
submit_node        — clicks submit, closes browser
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

from agents.state import AgentState, FieldResolutionResult
from browser.session import BrowserSession


def _save_cover_letter_pdf(text: str, company: str) -> Optional[str]:
    """Save the generated cover letter text as a PDF file for upload."""
    if not text:
        return None
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.units import inch

        safe_company = re.sub(r"[^\w]", "_", (company or "company").lower())[:20]
        out_dir = Path("assets/cover_letters")
        out_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(out_dir / f"cover_letter_{safe_company}.pdf")

        doc = SimpleDocTemplate(
            output_path, pagesize=letter,
            leftMargin=inch, rightMargin=inch,
            topMargin=inch, bottomMargin=inch,
        )
        style = ParagraphStyle("Body", fontSize=11, leading=16)
        story = []
        for line in text.splitlines():
            if line.strip():
                safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                story.append(Paragraph(safe, style))
            else:
                story.append(Spacer(1, 8))
        doc.build(story)
        return output_path
    except Exception as exc:
        print(f"  [fill_form] cover letter PDF save failed: {exc}")
        return None

# Shared browser session — lives for the duration of one job run
_session: Optional[BrowserSession] = None


def _get_handler(platform: str, session: BrowserSession):
    """Return the right ATS handler for the detected platform."""
    from browser.ats.workday import WorkdayHandler
    from browser.ats.greenhouse import GreenhouseHandler
    from browser.ats.linkedin import LinkedInHandler

    handlers = {
        "workday":    WorkdayHandler,
        "greenhouse": GreenhouseHandler,
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
            state["job_url"], wait_until="domcontentloaded", timeout=30_000
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

    # Recover from "Something went wrong" error pages (e.g. Workday transient error
    # that appears *after* navigate_to_apply returns, once the wizard's internal API
    # call fails).  Uses domcontentloaded (not networkidle) so Workday's long-poll
    # XHRs don't add 10+ seconds to every reload.
    for _err_attempt in range(3):
        try:
            _page_text = await _session.page.evaluate("() => document.documentElement.innerText")
            if "something went wrong" not in (_page_text or "").lower():
                break
        except Exception:
            break

        print(f"  [fill_form] 'Something went wrong' page (attempt {_err_attempt + 1}) — reloading")
        try:
            await _session.page.reload(wait_until="domcontentloaded", timeout=10_000)
        except Exception as _rel_exc:
            print(f"  [fill_form] reload error: {_rel_exc}")

        try:
            await _session.page.wait_for_selector(
                "[data-automation-id='formField'], input[type='text']",
                timeout=4_000,
            )
        except Exception:
            pass
    else:
        try:
            _page_text = await _session.page.evaluate("() => document.documentElement.innerText")
            if "something went wrong" in (_page_text or "").lower():
                print("  [fill_form] page still broken after 3 reloads — failing job")
                return {"status": "failed", "error": "Workday page error persists after reload attempts"}
        except Exception:
            pass

    platform = state.get("ats_platform", "unknown")
    handler = _get_handler(platform, _session)

    profile = state.get("user_profile") or {}
    job_description = state.get("job_description") or ""
    job_title = state.get("job_title") or "Software Engineer"
    hitl_threshold = float(os.getenv("LLM_CONFIDENCE_THRESHOLD", "0.7"))

    # Always reload custom_answers from DB so HITL answers are visible immediately
    # without requiring a stale state dict to be updated.
    if profile:
        from database.connection import get_session as _db_session
        from database.models import CustomAnswer as _CA
        user_id = state.get("user_id", 1)
        try:
            with _db_session() as _sess:
                rows = _sess.query(_CA).filter_by(user_id=user_id).all()
                profile = {**profile, "custom_answers": {r.key: r.value for r in rows}}
        except Exception:
            pass

    from agents.nodes.field_resolver import resolve_field

    resolved_fields: list = list(state.get("resolved_fields") or [])
    unanswered_fields: list = list(state.get("unanswered_fields") or [])

    # Labels already resolved in a prior HITL iteration — skip them to avoid
    # re-filling fields and re-triggering HITL for the same field.
    already_resolved_labels: set = {
        r.get("field_label", "") for r in resolved_fields
    }

    # Extract fields on the current page section
    raw_fields = await handler.extract_form_fields()

    if not raw_fields:
        print(f"  [fill_form] no fields found on current section — trying to advance")
        has_next = await handler.next_section()
        if has_next:
            print(f"  [fill_form] advanced past empty section")
            return {
                "resolved_fields": [],
                "pending_hitl_field": None,
                "form_complete": False,
            }
        print(f"  [fill_form] no fields and no next button — marking complete")
        return {
            "resolved_fields": resolved_fields,
            "pending_hitl_field": None,
            "form_complete": True,
        }

    print(f"  [fill_form] resolving {len(raw_fields)} fields")

    for field in raw_fields:
        label = field.get("label", "")
        locator = field.get("locator", "")
        field_type = field.get("field_type", "text")

        # Skip fields already resolved in a prior HITL iteration
        if label and label in already_resolved_labels:
            print(f"    skipping already-resolved '{label}'")
            continue

        # Skip pre-filled fields (LinkedIn pre-fills contact info from profile)
        current_value = field.get("current_value", "")
        if current_value:
            print(f"    skipping pre-filled '{label}' = '{current_value[:40]}'")
            resolved_fields.append({
                "field_label": label,
                "field_type": field_type,
                "field_locator": locator,
                "resolved_value": current_value,
                "resolution_source": "prefilled",
                "confidence": 1.0,
                "context": "pre-filled by ATS",
            })
            continue

        # File fields — use generated pipeline files directly, never LLM/HITL
        if field_type == "file":
            label_lower = label.lower()
            file_path = None
            source = "skipped"
            if "resume" in label_lower or "cv" in label_lower:
                file_path = state.get("tailored_resume_path")
                source = "tailored_resume"
            elif "cover" in label_lower:
                file_path = _save_cover_letter_pdf(
                    state.get("cover_letter"), state.get("job_company", "")
                )
                source = "cover_letter"

            if file_path and os.path.exists(file_path):
                success = await handler.fill_field(locator, file_path, "file")
                print(f"    {'filled' if success else 'failed'} '{label}' = '{file_path}' [{source}]")
            else:
                print(f"    [fill_form] skipping file field '{label}' — no file available")

            resolved_fields.append({
                "field_label": label,
                "field_type": "file",
                "field_locator": locator,
                "resolved_value": file_path,
                "resolution_source": source,
                "confidence": 1.0 if file_path else 0.0,
                "context": "file from pipeline state",
            })
            continue

        # Resolve non-file fields through the 4-step chain
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

        # Fill the field (resolved_value="" is valid — e.g. searchbox picks first option)
        if result["resolved_value"] is not None and locator:
            success = await handler.fill_field(
                locator, result["resolved_value"], field_type
            )
            if success:
                print(f"    filled '{label}' = '{result['resolved_value'][:40]}' "
                      f"[{result['resolution_source']}]")
            else:
                print(f"    failed to fill '{label}'")

        resolved_fields.append(result)

    # Try to advance to next section.
    # next_section() returns:
    #   True  — advanced successfully (new section loaded)
    #   False — button clicked but validation error (stayed on same section)
    #   None  — no Next/Save button found (truly at the end)
    has_next = await handler.next_section()

    if has_next is True:
        print(f"  [fill_form] advanced to next section")
        return {
            "resolved_fields": [],
            "pending_hitl_field": None,
            "unanswered_fields": unanswered_fields,
            "form_complete": False,
            "retry_count": 0,
        }

    if has_next is False:
        # Validation error — Workday rejected the section; retry up to 3 times
        retry_count = state.get("retry_count", 0) + 1
        print(f"  [fill_form] validation error on section — retry {retry_count}/3")
        if retry_count >= 3:
            print(f"  [fill_form] giving up after 3 retries — marking failed")
            return {
                "status": "failed",
                "error": "Workday validation error persists after 3 retries",
                "form_complete": False,
            }
        return {
            "resolved_fields": [],   # clear so retry re-fills the section
            "pending_hitl_field": None,
            "unanswered_fields": unanswered_fields,
            "form_complete": False,
            "retry_count": retry_count,
        }

    # has_next is None — no button found → all sections complete
    print(f"  [fill_form] all sections complete")
    return {
        "resolved_fields": resolved_fields,
        "pending_hitl_field": None,
        "unanswered_fields": unanswered_fields,
        "form_complete": True,
        "retry_count": 0,
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

    # Clean up generated files after successful submission
    if success:
        for key in ("tailored_resume_path",):
            path = state.get(key)
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    print(f"  [submit] deleted {path}")
                except Exception as exc:
                    print(f"  [submit] could not delete {path}: {exc}")

        # Cover letter PDF is saved under assets/cover_letters/
        company = state.get("job_company", "")
        safe_company = re.sub(r"[^\w]", "_", company.lower())[:20]
        cl_path = Path("assets/cover_letters") / f"cover_letter_{safe_company}.pdf"
        if cl_path.exists():
            try:
                cl_path.unlink()
                print(f"  [submit] deleted {cl_path}")
            except Exception as exc:
                print(f"  [submit] could not delete {cl_path}: {exc}")

    return {"status": "submitted" if success else "failed"}
