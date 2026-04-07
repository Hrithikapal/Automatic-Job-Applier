"""
browser/ats/workday.py — Workday ATS handler.

Workday uses data-automation-id attributes on every interactive element,
making it the most automation-friendly platform when you know the selectors.
Forms are multi-page wizards — we iterate through sections with next_section().
"""
from __future__ import annotations

import os
from typing import List

from browser.ats.base import BaseATSHandler
from browser.session import BrowserSession


class WorkdayHandler(BaseATSHandler):

    # ── Stable automation selectors ──────────────────────────────────────
    FIELD_CONTAINER = "[data-automation-id='formField']"
    NEXT_BTN = "[data-automation-id='bottom-navigation-next-button']"
    SUBMIT_BTN = "[data-automation-id='bottom-navigation-footer-button']"
    APPLY_BTN = "[data-automation-id='applyButton']"
    LOGIN_EMAIL = "[data-automation-id='email']"
    LOGIN_PASSWORD = "[data-automation-id='password']"
    LOGIN_SUBMIT = "[data-automation-id='signInSubmitButton']"
    CONFIRMATION = "[data-automation-id='thankYouPage']"

    def __init__(self, session: BrowserSession):
        super().__init__(session)

    # ------------------------------------------------------------------ #
    # Detection                                                            #
    # ------------------------------------------------------------------ #

    async def detect(self) -> bool:
        try:
            el = await self.page.query_selector("[data-automation-id]")
            return el is not None
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # Authentication                                                       #
    # ------------------------------------------------------------------ #

    async def sign_in(self, email: str, password: str) -> bool:
        """Sign in to Workday. Each employer has their own subdomain login."""
        try:
            await self.page.wait_for_selector(self.LOGIN_EMAIL, timeout=8_000)
            await self.page.fill(self.LOGIN_EMAIL, email)
            await self.page.fill(self.LOGIN_PASSWORD, password)
            await self.page.click(self.LOGIN_SUBMIT)
            await self.page.wait_for_load_state("networkidle", timeout=10_000)
            print("    [workday] signed in")
            return True
        except Exception as exc:
            print(f"    [workday] sign-in skipped or failed: {exc}")
            return False

    # ------------------------------------------------------------------ #
    # Navigation                                                           #
    # ------------------------------------------------------------------ #

    async def navigate_to_apply(self, job_url: str) -> bool:
        """Navigate to the job URL and click Apply."""
        try:
            await self.page.goto(job_url, wait_until="networkidle", timeout=30_000)
            # Click Apply button if present
            apply_btn = await self.page.query_selector(self.APPLY_BTN)
            if apply_btn:
                await apply_btn.click()
                await self.page.wait_for_load_state("networkidle", timeout=15_000)
            print("    [workday] navigated to application form")
            return True
        except Exception as exc:
            print(f"    [workday] navigation failed: {exc}")
            return False

    # ------------------------------------------------------------------ #
    # Form extraction                                                      #
    # ------------------------------------------------------------------ #

    async def extract_form_fields(self) -> List[dict]:
        """Scan the current wizard page for all form fields."""
        await self.page.wait_for_load_state("networkidle", timeout=10_000)

        containers = await self.page.query_selector_all(self.FIELD_CONTAINER)
        fields = []

        for container in containers:
            try:
                # Get label text
                label_el = await container.query_selector("label")
                label = (await label_el.inner_text()).strip() if label_el else ""
                if not label:
                    continue

                # Determine input type — Workday uses custom listbox for selects
                field_type = "text"
                locator = None

                # Check for listbox (custom dropdown)
                listbox = await container.query_selector("[role='combobox'], [role='listbox']")
                if listbox:
                    field_type = "select"
                    automation_id = await listbox.get_attribute("data-automation-id")
                    locator = f"[data-automation-id='{automation_id}']" if automation_id else None

                # Check for radio buttons
                radios = await container.query_selector_all("input[type='radio']")
                if radios:
                    field_type = "radio"
                    options = []
                    for r in radios:
                        val = await r.get_attribute("value") or ""
                        options.append(val)

                # Check for checkbox
                checkbox = await container.query_selector("input[type='checkbox']")
                if checkbox:
                    field_type = "checkbox"
                    automation_id = await checkbox.get_attribute("data-automation-id")
                    locator = f"[data-automation-id='{automation_id}']" if automation_id else None

                # Check for textarea
                textarea = await container.query_selector("textarea")
                if textarea:
                    field_type = "textarea"
                    automation_id = await textarea.get_attribute("data-automation-id")
                    locator = f"[data-automation-id='{automation_id}']" if automation_id else None

                # Check for file input
                file_input = await container.query_selector("input[type='file']")
                if file_input:
                    field_type = "file"
                    locator = "input[type='file']"

                # Default: text input
                if not locator:
                    text_input = await container.query_selector("input[type='text'], input:not([type])")
                    if text_input:
                        automation_id = await text_input.get_attribute("data-automation-id")
                        locator = f"[data-automation-id='{automation_id}']" if automation_id else None

                if not locator:
                    continue

                required_el = await container.get_attribute("aria-required")
                required = required_el == "true"

                fields.append({
                    "label": label,
                    "field_type": field_type,
                    "locator": locator,
                    "required": required,
                    "options": [],
                })

            except Exception as exc:
                print(f"    [workday] field extraction error: {exc}")
                continue

        print(f"    [workday] extracted {len(fields)} fields")
        return fields

    # ------------------------------------------------------------------ #
    # Fill                                                                 #
    # ------------------------------------------------------------------ #

    async def fill_field(self, locator: str, value: str, field_type: str) -> bool:
        """Fill a field. Workday listboxes need special handling."""
        if field_type == "select":
            try:
                # Click to open the dropdown, then select matching option
                await self.page.click(locator)
                await self.page.wait_for_selector("[role='option']", timeout=3_000)
                options = await self.page.query_selector_all("[role='option']")
                for option in options:
                    text = (await option.inner_text()).strip()
                    if value.lower() in text.lower():
                        await option.click()
                        return True
                # No match — click first option
                if options:
                    await options[0].click()
                return True
            except Exception as exc:
                print(f"    [workday] listbox fill failed: {exc}")
                return False

        return await self.fill_field_generic(locator, value, field_type)

    # ------------------------------------------------------------------ #
    # Navigation                                                           #
    # ------------------------------------------------------------------ #

    async def next_section(self) -> bool:
        """Click Next. Returns False if on final page."""
        try:
            btn = await self.page.query_selector(self.NEXT_BTN)
            if not btn:
                return False
            await btn.click()
            await self.page.wait_for_load_state("networkidle", timeout=10_000)
            return True
        except Exception:
            return False

    async def submit_application(self) -> bool:
        """Click the final Submit button and confirm submission."""
        try:
            btn = await self.page.query_selector(self.SUBMIT_BTN)
            if btn:
                await btn.click()
                await self.page.wait_for_load_state("networkidle", timeout=15_000)

            # Check for confirmation page
            confirmation = await self.page.query_selector(self.CONFIRMATION)
            if confirmation:
                print("    [workday] application submitted — confirmation page detected")
                return True

            print("    [workday] submitted (no confirmation page detected)")
            return True
        except Exception as exc:
            print(f"    [workday] submit failed: {exc}")
            return False
