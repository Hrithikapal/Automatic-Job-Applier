"""
browser/ats/base.py — Abstract base class for all ATS handlers.

Every ATS platform (Workday, Greenhouse, Lever, LinkedIn) implements
this interface. The form_filler node calls only these methods —
it never knows which platform it's talking to.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from browser.session import BrowserSession


class BaseATSHandler(ABC):
    """
    Abstract ATS handler. One concrete subclass per platform.

    All methods are async to match Playwright's async API.
    """

    def __init__(self, session: BrowserSession):
        self.session = session
        self.page = session.page

    # ------------------------------------------------------------------ #
    # Detection                                                            #
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def detect(self) -> bool:
        """Return True if the current page belongs to this ATS platform."""
        pass

    # ------------------------------------------------------------------ #
    # Authentication                                                       #
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def sign_in(self, email: str, password: str) -> bool:
        """Perform login. Return True if successful."""
        pass

    # ------------------------------------------------------------------ #
    # Navigation                                                           #
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def navigate_to_apply(self, job_url: str) -> bool:
        """Navigate to the application form start. Return True if reached."""
        pass

    # ------------------------------------------------------------------ #
    # Form interaction                                                     #
    # ------------------------------------------------------------------ #

    @abstractmethod
    async def extract_form_fields(self) -> List[dict]:
        """
        Scan the current page/section for all form fields.

        Returns a list of dicts:
            {
                "label":    str,        # visible field label
                "field_type": str,      # text|textarea|select|radio|checkbox|file
                "locator":  str,        # Playwright selector
                "required": bool,
                "options":  list[str],  # for select/radio only
            }
        """
        pass

    @abstractmethod
    async def fill_field(self, locator: str, value: str, field_type: str) -> bool:
        """Fill a single field. Return True if successful."""
        pass

    @abstractmethod
    async def next_section(self) -> bool:
        """
        Click Next/Continue to advance to the next form section.
        Return False if already on the final page (no Next button).
        """
        pass

    @abstractmethod
    async def submit_application(self) -> bool:
        """Click the final Submit button. Return True if confirmed."""
        pass

    # ------------------------------------------------------------------ #
    # Shared helpers available to all subclasses                          #
    # ------------------------------------------------------------------ #

    async def fill_field_generic(
        self, locator: str, value: str, field_type: str
    ) -> bool:
        """
        Generic field-filling logic usable by all subclasses.
        Handles: text, textarea, email, tel, number, url, select, radio,
                 checkbox, file upload.
        """
        page = self.page
        try:
            match field_type.lower():
                case "text" | "email" | "tel" | "number" | "url":
                    await page.fill(locator, value)
                case "textarea":
                    await page.fill(locator, value)
                case "select":
                    try:
                        await page.select_option(locator, label=value)
                    except Exception:
                        await page.select_option(locator, value=value)
                case "radio":
                    # Try to click the option whose label matches the value
                    await page.check(f"{locator}[value='{value}']")
                case "checkbox":
                    if value.lower() in ("yes", "true", "1", "on"):
                        await page.check(locator)
                    else:
                        await page.uncheck(locator)
                case "file":
                    await page.set_input_files(locator, value)
                case _:
                    # Fallback: try plain fill
                    await page.fill(locator, value)
            return True
        except Exception as exc:
            print(f"    [fill_generic] failed for {locator!r}: {exc}")
            return False

    async def wait_for_navigation(self, timeout: int = 10_000) -> None:
        """Wait for page to reach network idle state."""
        await self.page.wait_for_load_state("networkidle", timeout=timeout)
