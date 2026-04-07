"""
agents/nodes/job_scraper.py — Scrape job description from the job URL.

Strategy:
  1. Try a plain httpx GET (fast, no browser needed)
  2. Parse with BeautifulSoup — look for common JD containers
  3. If content is too short (<200 chars), fall back to Playwright
     and wait for JS-rendered content
"""
from __future__ import annotations

import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from agents.state import AgentState


# Common CSS selectors where job descriptions live across ATS platforms
JD_SELECTORS = [
    # Generic
    "main",
    '[class*="job-description"]',
    '[class*="jobDescription"]',
    '[id*="job-description"]',
    '[class*="job-detail"]',
    '[class*="posting-description"]',
    # Workday
    '[data-automation-id="jobPostingDescription"]',
    # Greenhouse
    "#content",
    ".job__description",
    # Lever
    ".posting-description",
    # LinkedIn
    ".jobs-description",
    ".job-view-layout",
    # Amazon
    ".job-detail-description",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

MIN_CONTENT_LENGTH = 200  # below this → trigger Playwright fallback


def _extract_text_from_html(html: str) -> Optional[str]:
    """Try each JD selector in order; return cleaned text from first match."""
    soup = BeautifulSoup(html, "html.parser")

    for selector in JD_SELECTORS:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(separator="\n", strip=True)
            if len(text) >= MIN_CONTENT_LENGTH:
                return _clean_text(text)

    # Fallback: grab all visible body text
    body = soup.find("body")
    if body:
        text = body.get_text(separator="\n", strip=True)
        if len(text) >= MIN_CONTENT_LENGTH:
            return _clean_text(text)

    return None


def _clean_text(text: str) -> str:
    """Remove excessive whitespace and blank lines."""
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    # Collapse runs of 3+ blank lines into 2
    result = []
    blank_count = 0
    for line in lines:
        if not line:
            blank_count += 1
            if blank_count <= 2:
                result.append(line)
        else:
            blank_count = 0
            result.append(line)
    return "\n".join(result)


async def _scrape_with_playwright(url: str) -> Optional[str]:
    """Playwright fallback for JS-rendered pages."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(
            user_agent=HEADERS["User-Agent"]
        )
        try:
            await page.goto(url, wait_until="networkidle", timeout=30_000)

            # Try each selector
            for selector in JD_SELECTORS:
                try:
                    el = await page.query_selector(selector)
                    if el:
                        text = await el.inner_text()
                        if len(text) >= MIN_CONTENT_LENGTH:
                            return _clean_text(text)
                except Exception:
                    continue

            # Fallback to full body text
            text = await page.inner_text("body")
            return _clean_text(text) if text else None
        finally:
            await browser.close()


async def scrape_jd_node(state: AgentState) -> dict:
    """
    Scrape the job description from state['job_url'].
    Updates: job_description, job_title (if detectable), job_company (if detectable).
    """
    url = state["job_url"]
    print(f"  [scrape_jd] fetching {url}")

    job_description: Optional[str] = None

    # ── Pass 1: plain HTTP ───────────────────────────────────────────────
    try:
        async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15) as client:
            response = await client.get(url)
            if response.status_code == 200:
                job_description = _extract_text_from_html(response.text)
    except Exception as exc:
        print(f"  [scrape_jd] HTTP fetch failed: {exc}")

    # ── Pass 2: Playwright fallback ──────────────────────────────────────
    if not job_description or len(job_description) < MIN_CONTENT_LENGTH:
        print(f"  [scrape_jd] falling back to Playwright")
        try:
            job_description = await _scrape_with_playwright(url)
        except Exception as exc:
            print(f"  [scrape_jd] Playwright fallback failed: {exc}")

    if not job_description:
        job_description = f"Could not scrape job description from: {url}"
        print(f"  [scrape_jd] could not extract description")
    else:
        print(f"  [scrape_jd] extracted {len(job_description)} chars")

    return {
        "job_description": job_description,
        "job_title": state.get("job_title"),
        "job_company": state.get("job_company"),
    }
