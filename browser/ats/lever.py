"""
browser/ats/lever.py — Lever ATS handler.

Lever hosts jobs at jobs.lever.co/{company}/{job-id}.
The application form is a single-page React app with standard HTML inputs.
EEO/demographic questions appear in a collapsible section at the bottom.
"""
from __future__ import annotations

import os
from typing import List

from browser.ats.base import BaseATSHandler
from browser.session import BrowserSession


class LeverHandler(BaseATSHandler):

    FORM_SELECTOR = ".application-form, form.posting-application, #application-form"
    SUBMIT_BTN = ".template-btn-submit, button[type='submit'], input[type='submit']"
    CONFIRMATION_SELECTORS = [
        ".confirmation-message",
        ".posting-thanks",
        "[class*='thank']",
        "[class*='success']",
    ]

    def __init__(self, session: BrowserSession):
        super().__init__(session)

    # ------------------------------------------------------------------ #
    # Detection                                                            #
    # ------------------------------------------------------------------ #

    async def detect(self) -> bool:
        try:
            el = await self.page.query_selector(".application-form, .posting-apply, [class*='lever']")
            return el is not None
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # Authentication                                                       #
    # ------------------------------------------------------------------ #

    async def sign_in(self, email: str, password: str) -> bool:
        """Lever job boards are public — no sign-in required."""
        print("    [lever] no sign-in required for public job boards")
        return True

    # ------------------------------------------------------------------ #
    # Navigation                                                           #
    # ------------------------------------------------------------------ #

    async def navigate_to_apply(self, job_url: str) -> bool:
        """Navigate to the Lever job URL and click Apply if needed."""
        try:
            await self.page.goto(job_url, wait_until="networkidle", timeout=30_000)

            # Click Apply button if present (some postings show JD first)
            apply_btn = await self.page.query_selector(
                ".template-btn-submit, a[href*='apply'], .posting-btn-submit"
            )
            if apply_btn:
                await apply_btn.click()
                await self.page.wait_for_load_state("networkidle", timeout=10_000)

            print("    [lever] navigated to application form")
            return True
        except Exception as exc:
            print(f"    [lever] navigation failed: {exc}")
            return False

    # ------------------------------------------------------------------ #
    # Form extraction                                                      #
    # ------------------------------------------------------------------ #

    async def extract_form_fields(self) -> List[dict]:
        """Extract all fields from the Lever application form."""
        await self.page.wait_for_load_state("networkidle", timeout=10_000)

        # Expand EEO section if collapsed
        try:
            eeo_toggle = await self.page.query_selector(
                ".eeo-section summary, [class*='demographic'] summary"
            )
            if eeo_toggle:
                await eeo_toggle.click()
        except Exception:
            pass

        fields = []
        field_groups = await self.page.query_selector_all(
            ".application-field, .application-form .field, .form-field"
        )

        for group in field_groups:
            try:
                # Get label
                label_el = await group.query_selector("label")
                if not label_el:
                    continue
                label_text = (await label_el.inner_text()).strip().replace("*", "").strip()
                if not label_text:
                    continue

                # Determine input
                select_el = await group.query_selector("select")
                textarea_el = await group.query_selector("textarea")
                file_el = await group.query_selector("input[type='file']")
                radio_els = await group.query_selector_all("input[type='radio']")
                checkbox_el = await group.query_selector("input[type='checkbox']")
                input_el = await group.query_selector("input[type='text'], input[type='email'], input[type='tel'], input:not([type])")

                if select_el:
                    field_type = "select"
                    name = await select_el.get_attribute("name") or ""
                    locator = f"select[name='{name}']" if name else "select"
                    options = await self._get_select_options(locator)
                elif textarea_el:
                    field_type = "textarea"
                    name = await textarea_el.get_attribute("name") or ""
                    locator = f"textarea[name='{name}']" if name else "textarea"
                    options = []
                elif file_el:
                    field_type = "file"
                    locator = "input[type='file']"
                    options = []
                elif radio_els:
                    field_type = "radio"
                    locator = ""
                    options = []
                    for r in radio_els:
                        val = await r.get_attribute("value") or ""
                        if val:
                            options.append(val)
                    if options:
                        name = await radio_els[0].get_attribute("name") or ""
                        locator = f"input[name='{name}']"
                elif checkbox_el:
                    field_type = "checkbox"
                    name = await checkbox_el.get_attribute("name") or ""
                    locator = f"input[type='checkbox'][name='{name}']" if name else "input[type='checkbox']"
                    options = []
                elif input_el:
                    field_type = "text"
                    input_type = await input_el.get_attribute("type") or "text"
                    name = await input_el.get_attribute("name") or ""
                    locator = f"input[name='{name}']" if name else f"input[type='{input_type}']"
                    options = []
                    if input_type == "email":
                        field_type = "email"
                else:
                    continue

                required_attr = await group.query_selector("[required], [aria-required='true']")
                required = required_attr is not None

                fields.append({
                    "label": label_text,
                    "field_type": field_type,
                    "locator": locator,
                    "required": required,
                    "options": options,
                })

            except Exception as exc:
                print(f"    [lever] field extraction error: {exc}")
                continue

        print(f"    [lever] extracted {len(fields)} fields")
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
        """Lever forms are single-page — no next section."""
        return False

    async def submit_application(self) -> bool:
        """Click Submit and wait for confirmation."""
        try:
            btn = await self.page.query_selector(self.SUBMIT_BTN)
            if not btn:
                print("    [lever] submit button not found")
                return False

            await btn.click()
            await self.page.wait_for_load_state("networkidle", timeout=15_000)

            for selector in self.CONFIRMATION_SELECTORS:
                el = await self.page.query_selector(selector)
                if el:
                    print("    [lever] application submitted — confirmation detected")
                    return True

            print("    [lever] submitted (confirmation not confirmed)")
            return True
        except Exception as exc:
            print(f"    [lever] submit failed: {exc}")
            return False
