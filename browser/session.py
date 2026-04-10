"""
browser/session.py — Playwright browser lifecycle manager.

Provides a single BrowserSession that persists across the full pipeline
for one job. Reuses the same page object through all ATS handler calls.
"""
from __future__ import annotations

import os
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright


class BrowserSession:
    """
    Manages one Playwright browser instance per job run.

    Usage:
        session = BrowserSession()
        await session.start()
        await session.page.goto("https://example.com")
        await session.close()
    """

    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def start(self, headless: Optional[bool] = None) -> None:
        """Launch Chromium and open a new page."""
        if headless is None:
            headless = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"

        slow_mo = int(os.getenv("BROWSER_SLOW_MO", "300"))  # ms between actions

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=headless,
            slow_mo=slow_mo,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
            locale="en-US",
        )

        # Hide automation fingerprints so sites serve their normal page
        await self._context.add_init_script("""
            // Remove navigator.webdriver flag
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
            // Ensure window.chrome exists (missing in automation mode)
            if (!window.chrome) {
                window.chrome = { runtime: {} };
            }
            // Override permissions query to behave like a real browser
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) =>
                parameters.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : originalQuery(parameters);
        """)

        self.page = await self._context.new_page()

    async def close(self) -> None:
        """Clean up browser resources."""
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._browser = None
        self._playwright = None
        self.page = None

    @property
    def is_open(self) -> bool:
        return self.page is not None
