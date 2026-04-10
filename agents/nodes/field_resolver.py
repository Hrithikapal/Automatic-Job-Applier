"""
agents/nodes/field_resolver.py — Resolve a form field value through a 4-step chain.

Precedence:
  1. Profile DB   — direct lookup for canonical fields (name, email, phone, etc.)
  2. Custom answers — fuzzy key match against custom_answers table (threshold 0.7)
  3. LLM inference  — LLM infers answer + confidence score
  4. HITL           — returned as pending if confidence < threshold

Returns a FieldResolutionResult for each field.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from agents.state import AgentState, FieldResolutionResult

# ---------------------------------------------------------------------------
# Step 1 — Static profile field map
# Maps normalised label tokens → lambda(profile) → value
# ---------------------------------------------------------------------------

def _clean_phone(raw: str) -> str:
    """
    Strip phone number down to digits only.
    Only removes a leading country code if the raw number uses international
    E.164 format (starts with '+'). Local-format numbers (no '+') are returned
    as raw digits so the stored value reaches the form unchanged.
    Examples:
      "+1 (415) 555-0192"  → "4155550192"   (US, strips +1)
      "+91 98765 43210"    → "9876543210"    (India, strips +91)
      "04155 550 192"      → "04155550192"   (local format, kept as-is)
      "093911 36520"       → "09391136520"   (local format, kept as-is)
    """
    digits = re.sub(r"\D", "", raw)
    # Only strip country code when the raw number has an explicit '+' prefix
    if raw.strip().startswith("+") and len(digits) > 10:
        for cc_len in (1, 2, 3):          # try 1-digit CC first (+1), then 2 (+91), then 3
            candidate = digits[cc_len:]
            if 8 <= len(candidate) <= 10:
                return candidate
    return digits


def _extract_country_code(phone: str, location: str = "") -> str:
    """Return searchbox-friendly country name from phone number's E.164 prefix.
    Falls back to profile location if phone has no international prefix."""
    p = phone.strip()
    if p.startswith("+91") or p.startswith("0091"):
        return "India"
    if p.startswith("+1") or p.startswith("001"):
        return "United States"
    if p.startswith("+44"):
        return "United Kingdom"
    if p.startswith("+61"):
        return "Australia"
    if p.startswith("+49"):
        return "Germany"
    if p.startswith("+33"):
        return "France"
    if p.startswith("+86"):
        return "China"
    if p.startswith("+81"):
        return "Japan"
    if p.startswith("+65"):
        return "Singapore"
    if p.startswith("+971"):
        return "United Arab Emirates"
    if p.startswith("+966"):
        return "Saudi Arabia"
    # Fallback: infer from profile location string
    loc = location.lower()
    if "india" in loc:
        return "India"
    if "united states" in loc or " ca" in loc or " ny" in loc or " tx" in loc or " wa" in loc:
        return "United States"
    if "united kingdom" in loc or "england" in loc or "london" in loc:
        return "United Kingdom"
    if "australia" in loc or "sydney" in loc or "melbourne" in loc:
        return "Australia"
    if "germany" in loc or "berlin" in loc:
        return "Germany"
    if "france" in loc or "paris" in loc:
        return "France"
    if "singapore" in loc:
        return "Singapore"
    if "united arab emirates" in loc or "dubai" in loc or "uae" in loc:
        return "United Arab Emirates"
    return ""


PROFILE_FIELD_MAP: dict[str, callable] = {
    # Name variants
    "first_name":           lambda p: p["full_name"].split()[0],
    "firstname":            lambda p: p["full_name"].split()[0],
    "last_name":            lambda p: p["full_name"].split()[-1],
    "lastname":             lambda p: p["full_name"].split()[-1],
    "full_name":            lambda p: p["full_name"],
    "fullname":             lambda p: p["full_name"],
    "name":                 lambda p: p["full_name"],
    # Contact
    "email":                lambda p: p["email"],
    "email_address":        lambda p: p["email"],
    "phone":                lambda p: _clean_phone(p["phone"]),
    "phone_number":         lambda p: _clean_phone(p["phone"]),
    "mobile":               lambda p: _clean_phone(p["phone"]),
    "mobile_number":        lambda p: _clean_phone(p["phone"]),
    # Phone sub-fields (Workday wizard)
    "country_territory_phone_code": lambda p: _extract_country_code(p.get("phone", ""), p.get("location", "")),
    "country_phone_code":           lambda p: _extract_country_code(p.get("phone", ""), p.get("location", "")),
    "phone_device_type":            lambda p: "Mobile",
    "phone_extension":              lambda p: "",   # intentionally blank
    # "How did you hear" — always pick first dropdown option (value="" triggers first-pick in fill_field)
    "how_did_you_hear_about_this_job":      lambda p: "",
    "how_did_you_hear_about_us":            lambda p: "",
    "how_did_you_hear_about_this_position": lambda p: "",
    "how_did_you_hear":                     lambda p: "",
    "how_did_you_find_out_about_this_job":  lambda p: "",
    # Location
    "location":             lambda p: p["location"],
    "city":                 lambda p: p["location"].split(",")[0].strip(),
    "address":              lambda p: p["location"],
    "current_location":     lambda p: p["location"],
    # Online profiles
    "linkedin":             lambda p: p.get("linkedin_url", ""),
    "linkedin_url":         lambda p: p.get("linkedin_url", ""),
    "linkedin_profile":     lambda p: p.get("linkedin_url", ""),
    "github":               lambda p: p.get("github_url", ""),
    "github_url":           lambda p: p.get("github_url", ""),
    "portfolio":            lambda p: p.get("portfolio_url", ""),
    "website":              lambda p: p.get("portfolio_url", ""),
    "personal_website":     lambda p: p.get("portfolio_url", ""),
    # Summary
    "summary":              lambda p: p.get("summary", ""),
    "professional_summary": lambda p: p.get("summary", ""),
    "about":                lambda p: p.get("summary", ""),
    "bio":                  lambda p: p.get("summary", ""),
}


def _normalise_label(label: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace to underscores."""
    label = label.lower().strip()
    label = re.sub(r"[^\w\s]", "", label)
    label = re.sub(r"\s+", "_", label)
    return label


def _resolve_from_profile(
    label: str, profile: dict
) -> Optional[FieldResolutionResult]:
    """Return a result if the label directly maps to a profile field."""
    key = _normalise_label(label)
    if key in PROFILE_FIELD_MAP:
        try:
            value = PROFILE_FIELD_MAP[key](profile)
            if value is not None:
                return FieldResolutionResult(
                    field_label=label,
                    field_type="text",
                    field_locator="",
                    resolved_value=str(value),
                    resolution_source="profile",
                    confidence=1.0,
                    context="",
                )
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Step 2 — Custom answers fuzzy match
# ---------------------------------------------------------------------------

def _token_overlap(a: str, b: str) -> float:
    """Simple token overlap ratio between two strings."""
    tokens_a = set(re.split(r"[\s_\-]+", a.lower()))
    tokens_b = set(re.split(r"[\s_\-]+", b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    return len(intersection) / max(len(tokens_a), len(tokens_b))


def _resolve_from_custom_answers(
    label: str, custom_answers: dict[str, str], threshold: float = 0.7
) -> Optional[FieldResolutionResult]:
    """Fuzzy-match label against custom answer keys."""
    normalised = _normalise_label(label)
    best_key = None
    best_score = 0.0

    for key in custom_answers:
        score = _token_overlap(normalised, key)
        if score > best_score:
            best_score = score
            best_key = key

    if best_key and best_score >= threshold:
        return FieldResolutionResult(
            field_label=label,
            field_type="text",
            field_locator="",
            resolved_value=custom_answers[best_key],
            resolution_source="custom_answer",
            confidence=best_score,
            context=f"matched key: {best_key} (score={best_score:.2f})",
        )
    return None


# ---------------------------------------------------------------------------
# Step 3 — LLM inference
# ---------------------------------------------------------------------------

async def _resolve_from_llm(
    label: str,
    field_type: str,
    options: list,
    profile: dict,
    job_description: str,
    job_title: str,
) -> FieldResolutionResult:
    """Ask the LLM to infer the best answer and return a confidence score."""
    from langchain_groq import ChatGroq
    from langchain_core.messages import HumanMessage, SystemMessage

    llm = ChatGroq(
        model="llama-3.3-70b-versatile",
        api_key=os.getenv("GROQ_API_KEY"),
        temperature=0.1,
        max_tokens=256,
    )

    options_str = f"\nAvailable options: {', '.join(options)}" if options else ""
    custom_answers_str = "\n".join(
        f"  {k}: {v}" for k, v in profile.get("custom_answers", {}).items()
    )

    system = (
        "You are filling out a job application form on behalf of a candidate. "
        "Given the candidate profile and a form field label, provide the best answer. "
        "Respond ONLY with valid JSON: {\"value\": \"...\", \"confidence\": 0.0}"
    )

    human = f"""CANDIDATE PROFILE SUMMARY:
Name: {profile.get('full_name')}
Location: {profile.get('location')}
Summary: {profile.get('summary', '')[:300]}
Custom answers on file:
{custom_answers_str}

JOB: {job_title}
JOB DESCRIPTION (excerpt): {job_description[:500]}

FORM FIELD:
Label: "{label}"
Type: {field_type}{options_str}

What value should be entered? Respond with JSON only."""

    try:
        response = await llm.ainvoke([
            SystemMessage(content=system),
            HumanMessage(content=human),
        ])
        raw = response.content.strip()
        # Extract JSON from response
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            value = str(data.get("value", "")).strip()
            confidence = float(data.get("confidence", 0.5))
        else:
            value = raw
            confidence = 0.4
    except Exception as exc:
        print(f"    [field_resolver] LLM call failed for '{label}': {exc}")
        value = ""
        confidence = 0.0

    return FieldResolutionResult(
        field_label=label,
        field_type=field_type,
        field_locator="",
        resolved_value=value if value else None,
        resolution_source="llm",
        confidence=confidence,
        context=f"llm inferred (confidence={confidence:.2f})",
    )


# ---------------------------------------------------------------------------
# Main resolver
# ---------------------------------------------------------------------------

async def resolve_field(
    field: dict,
    profile: dict,
    job_description: str,
    job_title: str,
    hitl_threshold: float,
) -> FieldResolutionResult:
    """
    Run the full 4-step resolution chain for a single form field.
    Returns a FieldResolutionResult with resolution_source indicating
    which step resolved it (or 'hitl' if it needs human input).
    """
    label = field.get("label", "")
    field_type = field.get("field_type", "text")
    locator = field.get("locator", "")
    options = field.get("options", [])
    custom_answers: dict = profile.get("custom_answers", {})

    # Step 1 — Profile DB
    result = _resolve_from_profile(label, profile)
    if result:
        result["field_type"] = field_type
        result["field_locator"] = locator
        return result

    # Step 2 — Custom answers
    result = _resolve_from_custom_answers(label, custom_answers)
    if result:
        result["field_type"] = field_type
        result["field_locator"] = locator
        return result

    # Step 3 — LLM inference
    result = await _resolve_from_llm(
        label, field_type, options, profile, job_description, job_title
    )
    result["field_locator"] = locator

    # Step 4 — Route to HITL if confidence too low
    if result["confidence"] < hitl_threshold or not result["resolved_value"]:
        result["resolution_source"] = "hitl"

    return result
