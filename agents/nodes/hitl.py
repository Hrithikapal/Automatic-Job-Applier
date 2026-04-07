"""
agents/nodes/hitl.py — Human-in-the-Loop with 30-second terminal countdown.

Triggered when field_resolver returns resolution_source == "hitl" (confidence
below LLM_CONFIDENCE_THRESHOLD or no basis to infer).

Flow:
  - Print field label, type, and context to terminal
  - Start a 30-second countdown in a background thread
  - If user types an answer in time:
      → save to custom_answers DB for future runs
      → clear pending_hitl_field, continue to fill_form
  - If timeout fires:
      → append field to unanswered_fields
      → set status = "backlog"
      → graph routes to record_result (job skipped, next job starts)

record_result_node — persists final job status + unanswered_fields to DB.
"""
from __future__ import annotations

import sys
import threading
from datetime import datetime
from typing import Optional

from agents.state import AgentState, FieldResolutionResult


# ---------------------------------------------------------------------------
# HITL node
# ---------------------------------------------------------------------------

async def hitl_node(state: AgentState) -> dict:
    """
    Prompt the user for a field value with a 30-second countdown.
    Non-blocking — uses threading.Event so the rest of the system
    can continue after timeout.
    """
    import os
    timeout = int(os.getenv("HITL_TIMEOUT_SECONDS", "30"))

    field: Optional[FieldResolutionResult] = state.get("pending_hitl_field")
    if not field:
        # Nothing to resolve — continue
        return {"pending_hitl_field": None}

    label = field.get("field_label", "Unknown field")
    field_type = field.get("field_type", "text")
    context = field.get("context", "")

    # ── Print HITL prompt ────────────────────────────────────────────────
    print("\n" + "═" * 60)
    print(f"  [HITL] Cannot resolve field with confidence")
    print(f"  Field : {label}")
    print(f"  Type  : {field_type}")
    if context:
        print(f"  Context: {context}")
    print(f"  ⏱  You have {timeout} seconds to answer (Enter to submit).")
    print(f"  Press Enter with no input to skip and backlog this job.")
    print("═" * 60)

    # ── Threading setup ──────────────────────────────────────────────────
    answered = threading.Event()
    user_input: list[str] = [""]  # mutable container for thread result

    def _prompt() -> None:
        try:
            sys.stdout.write(f"  Answer: ")
            sys.stdout.flush()
            line = sys.stdin.readline()
            user_input[0] = line.strip()
            answered.set()
        except Exception:
            answered.set()

    input_thread = threading.Thread(target=_prompt, daemon=True)
    input_thread.start()

    # Block (in thread-safe way) until answered or timeout
    answered_in_time = answered.wait(timeout=timeout)

    # ── Evaluate outcome ─────────────────────────────────────────────────
    answer = user_input[0].strip()

    if answered_in_time and answer:
        print(f"\n  [HITL] Answer received: '{answer}'")
        _save_to_custom_answers(
            user_id=state["user_id"],
            label=label,
            answer=answer,
        )

        # Update the resolved field and clear the pending flag
        updated_field: FieldResolutionResult = {
            **field,
            "resolved_value": answer,
            "resolution_source": "hitl",
            "confidence": 1.0,
        }

        resolved = list(state.get("resolved_fields") or [])
        resolved.append(updated_field)

        return {
            "pending_hitl_field": None,
            "resolved_fields": resolved,
            "status": "processing",
        }

    else:
        # Timeout or empty answer — move job to backlog
        elapsed = "timeout" if not answered_in_time else "skipped"
        print(f"\n  [HITL] {elapsed} — moving job to backlog")

        unanswered = list(state.get("unanswered_fields") or [])
        unanswered.append({
            "label": label,
            "field_type": field_type,
            "context": context,
            "hint": (
                f"Add this to custom_answers with key: "
                f"'{_normalise_key(label)}'"
            ),
        })

        return {
            "pending_hitl_field": None,
            "unanswered_fields": unanswered,
            "status": "backlog",
        }


# ---------------------------------------------------------------------------
# record_result_node
# ---------------------------------------------------------------------------

async def record_result_node(state: AgentState) -> dict:
    """
    Persist the final job status, failure reason, and unanswered fields to DB.
    Called at the end of every pipeline run — submitted, failed, or backlog.
    """
    from database.connection import get_session
    from database.models import Job

    job_id = state["job_id"]
    status = state.get("status", "failed")
    unanswered = state.get("unanswered_fields") or []
    error = state.get("error")

    with get_session() as session:
        job = session.get(Job, job_id)
        if job:
            job.status = status
            job.updated_at = datetime.utcnow()

            if error:
                job.failure_reason = error
            if unanswered:
                job.unanswered_fields = unanswered
            if state.get("tailored_resume"):
                job.tailored_resume_text = state["tailored_resume"]

            session.commit()

    icon = {"submitted": "✓", "backlog": "⚠", "failed": "✗"}.get(status, "?")
    print(f"  [record_result] {icon} job {job_id} → {status}")

    if status == "backlog" and unanswered:
        print(f"\n  Fields that need answers before next run:")
        for f in unanswered:
            print(f"    • {f['label']}  →  {f.get('hint', '')}")
        print()

    return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise_key(label: str) -> str:
    """Convert a field label to a custom_answers key format."""
    import re
    key = label.lower().strip()
    key = re.sub(r"[^\w\s]", "", key)
    key = re.sub(r"\s+", "_", key)
    return key


def _save_to_custom_answers(user_id: int, label: str, answer: str) -> None:
    """Persist a HITL answer to custom_answers so it's used on future runs."""
    from database.connection import get_session
    from database.models import CustomAnswer

    key = _normalise_key(label)

    try:
        with get_session() as session:
            # Update if key exists, otherwise insert
            existing = (
                session.query(CustomAnswer)
                .filter_by(user_id=user_id, key=key)
                .first()
            )
            if existing:
                existing.value = answer
                existing.updated_at = datetime.utcnow()
                print(f"  [HITL] Updated custom answer: {key} = '{answer}'")
            else:
                session.add(CustomAnswer(
                    user_id=user_id,
                    key=key,
                    value=answer,
                    notes="Captured via HITL during job application",
                ))
                print(f"  [HITL] Saved new custom answer: {key} = '{answer}'")
            session.commit()
    except Exception as exc:
        print(f"  [HITL] Failed to save custom answer: {exc}")
