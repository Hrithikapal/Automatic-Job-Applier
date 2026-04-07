"""
browser/ats/greenhouse.py — Greenhouse ATS handler.

Greenhouse uses standard HTML forms with stable name attributes.
The application form lives at /jobs/{id}/applications/new or
is embedded in boards.greenhouse.io/{company}/jobs/{id}.
Custom questions appear in a dedicated section below the standard fields.
"""
from __future__ import annotations

import os
from typing import List

from browser.ats.base import BaseATSHandler
from browser.session import BrowserSession


class GreenhouseHandler(BaseATSHandler):

    FORM_SELECTOR = "#application_form, form#application_form, .application--wrapper form"
    SUBMIT_BTN = "#submit_app, input[type='submit'], button[type='submit']"
    CONFIRMATION_SELECTORS = [
        ".confirmation",
        ".thanks",
        "#confirmation",
        "[class*='confirmation']",
    ]

    def __init__(self, session: BrowserSession):
        super().__init__(session)

    # ------------------------------------------------------------------ #
    # Detection                                                            #
    # ------------------------------------------------------------------ #

    async def detect(self) -> bool:
        try:
            el = await self.page.query_selector("#application_form, .application--wrapper")
            return el is not None
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # Authentication                                                       #
    # ------------------------------------------------------------------ #

    async def sign_in(self, email: str, password: str) -> bool:
        """
        Greenhouse boards are mostly public — no sign-in required.
        Returns True to allow the pipeline to continue.
        """
        print("    [greenhouse] no sign-in required for public boards")
        return True

    # ------------------------------------------------------------------ #
    # Navigation                                                           #
    # ------------------------------------------------------------------ #

    async def navigate_to_apply(self, job_url: str) -> bool:
        """Navigate to the Greenhouse job URL (form is on the same page)."""
        try:
            await self.page.goto(job_url, wait_until="networkidle", timeout=30_000)

            # Some boards have a separate "Apply" button that opens a modal
            apply_btn = await self.page.query_selector(
                "a[href*='application'], .apply-button, #apply-now"
            )
            if apply_btn:
                await apply_btn.click()
                await self.page.wait_for_load_state("networkidle", timeout=10_000)

            print("    [greenhouse] navigated to application form")
            return True
        except Exception as exc:
            print(f"    [greenhouse] navigation failed: {exc}")
            return False

    # ------------------------------------------------------------------ #
    # Form extraction                                                      #
    # ------------------------------------------------------------------ #

    async def extract_form_fields(self) -> List[dict]:
        """Extract all fields from the Greenhouse application form."""
        await self.page.wait_for_load_state("networkidle", timeout=10_000)

        fields = []

        # Standard fields — Greenhouse uses <label for="..."> + input id pairs
        labels = await self.page.query_selector_all(
            "#application_form label, .application--wrapper label"
        )

        for label_el in labels:
            try:
                label_text = (await label_el.inner_text()).strip()
                # Strip asterisk (required marker)
                label_text = label_text.replace("*", "").strip()
                if not label_text:
                    continue

                for_attr = await label_el.get_attribute("for")
                if not for_attr:
                    continue

                input_el = await self.page.query_selector(f"#{for_attr}")
                if not input_el:
                    continue

                tag = await input_el.evaluate("el => el.tagName.toLowerCase()")
                input_type = await input_el.get_attribute("type") or "text"

                if tag == "select":
                    field_type = "select"
                    options = await self._get_select_options(f"#{for_attr}")
                elif tag == "textarea":
                    field_type = "textarea"
                    options = []
                elif input_type == "file":
                    field_type = "file"
                    options = []
                elif input_type == "checkbox":
                    field_type = "checkbox"
                    options = []
                elif input_type == "radio":
                    field_type = "radio"
                    options = []
                else:
                    field_type = "text"
                    options = []

                required_el = await input_el.get_attribute("required")
                aria_required = await input_el.get_attribute("aria-required")
                required = required_el is not None or aria_required == "true"

                fields.append({
                    "label": label_text,
                    "field_type": field_type,
                    "locator": f"#{for_attr}",
                    "required": required,
                    "options": options,
                })

            except Exception as exc:
                print(f"    [greenhouse] field extraction error: {exc}")
                continue

        print(f"    [greenhouse] extracted {len(fields)} fields")
        return fields

    async def _get_select_options(self, locator: str) -> List[str]:
        try:
            options = await self.page.query_selector_all(f"{locator} option")
            return [
                (await o.inner_text()).strip()
                for o in options
                if (await o.get_attribute("value") or "").strip()
            ]
        except Exception:
            return []

    # ------------------------------------------------------------------ #
    # Fill                                                                 #
    # ------------------------------------------------------------------ #

    async def fill_field(self, locator: str, value: str, field_type: str) -> bool:
        return await self.fill_field_generic(locator, value, field_type)

    # ------------------------------------------------------------------ #
    # Navigation                                                           #
    # ------------------------------------------------------------------ #

    async def next_section(self) -> bool:
        """
        Greenhouse applications are typically single-page.
        Returns False to indicate no further sections.
        """
        return False

    async def submit_application(self) -> bool:
        """Click Submit and check for confirmation."""
        try:
            btn = await self.page.query_selector(self.SUBMIT_BTN)
            if not btn:
                print("    [greenhouse] submit button not found")
                return False

            await btn.click()
            await self.page.wait_for_load_state("networkidle", timeout=15_000)

            # Check for confirmation
            for selector in self.CONFIRMATION_SELECTORS:
                el = await self.page.query_selector(selector)
                if el:
                    print("    [greenhouse] application submitted — confirmation detected")
                    return True

            print("    [greenhouse] submitted (confirmation not confirmed)")
            return True
        except Exception as exc:
            print(f"    [greenhouse] submit failed: {exc}")
            return False
