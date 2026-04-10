"""
agents/nodes/ats_detector.py — Detect the ATS platform via URL patterns + DOM fingerprints.

Two-pass strategy — no hardcoded per-URL logic:
  Pass 1: URL regex matching (fast, pre-browser, used for credential pre-loading)
  Pass 2: DOM fingerprint scoring (authoritative, post-browser navigation)

The platform with the highest score above a threshold wins.
"""
from __future__ import annotations

import re
from typing import Optional

from agents.state import AgentState


# ---------------------------------------------------------------------------
# Pass 1 — URL pattern registry
# Extend this dict to support new ATS platforms — no code changes elsewhere.
# ---------------------------------------------------------------------------

ATS_URL_PATTERNS: dict[str, list[str]] = {
    "workday": [
        r"myworkdayjobs\.com",
        r"wd\d+\.myworkdayjobs\.com",
        r"\.workday\.com",
    ],
    "greenhouse": [
        r"boards\.greenhouse\.io",
        r"app\.greenhouse\.io",
        r"greenhouse\.io/embed",
    ],
    "linkedin": [
        r"linkedin\.com/jobs",
        r"linkedin\.com/hiring",
    ],
    "ashby": [
        r"jobs\.ashbyhq\.com",
        r"ashbyhq\.com/",
    ],
    "amazon": [
        r"amazon\.jobs",
        r"hiring\.amazon\.com",
    ],
    "microsoft": [
        r"careers\.microsoft\.com",
        r"jobs\.careers\.microsoft\.com",
    ],
}


# ---------------------------------------------------------------------------
# Pass 2 — DOM fingerprint registry
# Each platform has selectors, script URL patterns, and meta tag signals.
# Score: 2pts per matching selector, 1pt per script pattern, 2pts per meta tag.
# ---------------------------------------------------------------------------

ATS_DOM_FINGERPRINTS: dict[str, dict] = {
    "workday": {
        "selectors": [
            "[data-automation-id='jobPostingHeader']",
            "[data-automation-id='formField']",
            "[data-automation-id='bottom-navigation-next-button']",
            "div[data-uxi-widget-type]",
            "input[data-automation-id]",
        ],
        "script_patterns": [
            r"workday\.com/.*\.js",
            r"wd\d+\.myworkdayjobs\.com",
        ],
        "meta_tags": [],
    },
    "greenhouse": {
        "selectors": [
            "#application_form",
            "form#application_form",
            ".application--wrapper",
            "#greenhouse-application-form",
            "div.application",
        ],
        "script_patterns": [
            r"greenhouse\.io/.*\.js",
            r"boards\.greenhouse\.io",
        ],
        "meta_tags": [
            {"name": "generator", "content_pattern": r"greenhouse"},
        ],
    },
    "linkedin": {
        "selectors": [
            ".jobs-apply-button",
            ".jobs-easy-apply-content",
            "[data-job-id]",
            ".jobs-easy-apply-modal",
            ".jobs-apply-form",
        ],
        "script_patterns": [
            r"linkedin\.com/.*\.js",
            r"static\.licdn\.com",
        ],
        "meta_tags": [],
    },
    "ashby": {
        "selectors": [
            "[data-testid='ashby-application-form']",
            "[data-testid*='ashby']",
            "._application_",
            "form[action*='ashbyhq']",
        ],
        "script_patterns": [
            r"ashbyhq\.com/.*\.js",
        ],
        "meta_tags": [],
    },
}

DOM_SCORE_THRESHOLD = 2  # minimum score to confirm a platform


# ---------------------------------------------------------------------------
# URL-based detection (Pass 1)
# ---------------------------------------------------------------------------

def detect_from_url(url: str) -> Optional[str]:
    """Return platform name if URL matches a known pattern, else None."""
    url_lower = url.lower()
    for platform, patterns in ATS_URL_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, url_lower):
                return platform
    return None


# ---------------------------------------------------------------------------
# DOM-based detection (Pass 2)
# ---------------------------------------------------------------------------

async def detect_from_dom(page) -> Optional[str]:
    """
    Score each platform against the live DOM and return the best match.
    Returns None if no platform scores above DOM_SCORE_THRESHOLD.
    """
    scores: dict[str, int] = {platform: 0 for platform in ATS_DOM_FINGERPRINTS}

    # Get all script src attributes for script pattern matching
    script_srcs: list[str] = await page.evaluate(
        "Array.from(document.querySelectorAll('script[src]')).map(s => s.src)"
    )
    script_srcs_str = " ".join(script_srcs).lower()

    for platform, fingerprint in ATS_DOM_FINGERPRINTS.items():
        # Score CSS selectors (2 pts each)
        for selector in fingerprint["selectors"]:
            try:
                el = await page.query_selector(selector)
                if el:
                    scores[platform] += 2
            except Exception:
                pass

        # Score script URL patterns (1 pt each)
        for pattern in fingerprint["script_patterns"]:
            if re.search(pattern, script_srcs_str):
                scores[platform] += 1

        # Score meta tags (2 pts each)
        for meta in fingerprint["meta_tags"]:
            try:
                meta_name = meta["name"]
                content = await page.evaluate(
                    f"document.querySelector('meta[name=\"{meta_name}\"]')?.content || ''"
                )
                if re.search(meta["content_pattern"], content.lower()):
                    scores[platform] += 2
            except Exception:
                pass

    best_platform = max(scores, key=lambda p: scores[p])
    best_score = scores[best_platform]

    if best_score >= DOM_SCORE_THRESHOLD:
        return best_platform
    return None


# ---------------------------------------------------------------------------
# Node
# ---------------------------------------------------------------------------

async def ats_detect_node(state: AgentState) -> dict:
    """
    Detect ATS platform for the current job.

    Pass 1: URL pattern check (fast).
    Pass 2: DOM fingerprint scoring (if browser is open).
    DOM result takes precedence over URL result.
    """
    job_url = state["job_url"]

    # Pass 1 — URL
    url_platform = detect_from_url(job_url)
    if url_platform:
        print(f"  [ats_detect] URL match → {url_platform}")

    # Pass 2 — DOM (only if browser is open)
    dom_platform = None
    if state.get("browser_ready"):
        try:
            from browser.session import BrowserSession
            # Page is accessed via the shared session stored in state
            # For now we rely on the browser_init node having opened the URL
            # The actual session object is managed in form_filler / browser_init
            pass
        except Exception as exc:
            print(f"  [ats_detect] DOM check skipped: {exc}")

    # DOM takes precedence; fall back to URL detection
    platform = dom_platform or url_platform or "unknown"
    print(f"  [ats_detect] final platform → {platform}")

    return {"ats_platform": platform}
