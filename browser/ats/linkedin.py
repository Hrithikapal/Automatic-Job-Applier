"""
browser/ats/linkedin.py — LinkedIn Easy Apply handler.

LinkedIn Easy Apply is a multi-step modal dialog rendered entirely in React.
Fields use data-test-* attributes. Sign-in is handled at linkedin.com/login
and cookies are reused for the session.
"""
from __future__ import annotations

import os
from typing import List

from browser.ats.base import BaseATSHandler
from browser.session import BrowserSession


class LinkedInHandler(BaseATSHandler):

    LOGIN_URL = "https://www.linkedin.com/login"
    EMAIL_INPUT = "#username"
    PASSWORD_INPUT = "#password"
    LOGIN_BTN = "[data-litms-control-urn='login-submit'], button[type='submit']"
    EASY_APPLY_BTN = ".jobs-apply-button, [aria-label*='Easy Apply']"
    MODAL_SELECTOR = ".jobs-easy-apply-modal, .artdeco-modal"
    NEXT_BTN = "[aria-label='Continue to next step'], button[aria-label*='next']"
    REVIEW_BTN = "[aria-label='Review your application'], button[aria-label*='Review']"
    SUBMIT_BTN = "[aria-label='Submit application'], button[aria-label*='Submit']"
    CONFIRMATION = ".artdeco-inline-feedback--success, [class*='success-banner']"

    def __init__(self, session: BrowserSession):
        super().__init__(session)

    # ------------------------------------------------------------------ #
    # Detection                                                            #
    # ------------------------------------------------------------------ #

    async def detect(self) -> bool:
        try:
            el = await self.page.query_selector("[data-job-id], .jobs-apply-button")
            return el is not None
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # Authentication                                                       #
    # ------------------------------------------------------------------ #

    async def sign_in(self, email: str, password: str) -> bool:
        """Sign in to LinkedIn. Required before Easy Apply."""
        try:
            await self.page.goto(self.LOGIN_URL, wait_until="networkidle", timeout=20_000)

            # Check if already logged in
            if "feed" in self.page.url or "jobs" in self.page.url:
                print("    [linkedin] already signed in")
                return True

            await self.page.fill(self.EMAIL_INPUT, email)
            await self.page.fill(self.PASSWORD_INPUT, password)
            await self.page.click(self.LOGIN_BTN)
            await self.page.wait_for_load_state("networkidle", timeout=15_000)

            # Handle CAPTCHA or 2FA (cannot automate — log warning)
            if "checkpoint" in self.page.url or "challenge" in self.page.url:
                print("    [linkedin] 2FA or CAPTCHA required — manual intervention needed")
                return False

            print("    [linkedin] signed in successfully")
            return True
        except Exception as exc:
            print(f"    [linkedin] sign-in failed: {exc}")
            return False

    # ------------------------------------------------------------------ #
    # Navigation                                                           #
    # ------------------------------------------------------------------ #

    async def navigate_to_apply(self, job_url: str) -> bool:
        """Navigate to job URL and click Easy Apply to open the modal."""
        try:
            await self.page.goto(job_url, wait_until="networkidle", timeout=30_000)

            # Click Easy Apply button
            apply_btn = await self.page.wait_for_selector(
                self.EASY_APPLY_BTN, timeout=10_000
            )
            if apply_btn:
                await apply_btn.click()
                await self.page.wait_for_selector(self.MODAL_SELECTOR, timeout=8_000)
                print("    [linkedin] Easy Apply modal opened")
                return True

            print("    [linkedin] Easy Apply button not found")
            return False
        except Exception as exc:
            print(f"    [linkedin] navigation failed: {exc}")
            return False

    # ------------------------------------------------------------------ #
    # Form extraction                                                      #
    # ------------------------------------------------------------------ #

    async def extract_form_fields(self) -> List[dict]:
        """Extract fields from the current Easy Apply modal step."""
        await self.page.wait_for_load_state("networkidle", timeout=8_000)

        fields = []

        # LinkedIn uses labeled form groups inside the modal
        groups = await self.page.query_selector_all(
            ".jobs-easy-apply-form-section__grouping, "
            ".fb-form-element, "
            "[class*='form-component']"
        )

        for group in groups:
            try:
                label_el = await group.query_selector("label, legend")
                if not label_el:
                    continue
                label_text = (await label_el.inner_text()).strip().replace("*", "").strip()
                if not label_text:
                    continue

                # Detect field type
                select_el = await group.query_selector("select")
                textarea_el = await group.query_selector("textarea")
                file_el = await group.query_selector("input[type='file']")
                radio_els = await group.query_selector_all("input[type='radio']")
                text_el = await group.query_selector(
                    "input[type='text'], input[type='email'], input[type='tel'], input[type='number']"
                )

                if select_el:
                    field_type = "select"
                    locator = "select"
                    options = await self._get_select_options_in(group)
                elif textarea_el:
                    field_type = "textarea"
                    locator = "textarea"
                    options = []
                elif file_el:
                    field_type = "file"
                    locator = "input[type='file']"
                    options = []
                elif radio_els:
                    field_type = "radio"
                    options = []
                    for r in radio_els:
                        val = await r.get_attribute("value") or ""
                        if val:
                            options.append(val)
                    name = await radio_els[0].get_attribute("name") if radio_els else ""
                    locator = f"input[name='{name}']" if name else "input[type='radio']"
                elif text_el:
                    input_type = await text_el.get_attribute("type") or "text"
                    field_type = input_type
                    test_id = await text_el.get_attribute("data-test-single-typeahead-entity-form-component-id")
                    locator = (
                        f"[data-test-single-typeahead-entity-form-component-id='{test_id}']"
                        if test_id
                        else f"input[type='{input_type}']"
                    )
                    options = []
                else:
                    continue

                fields.append({
                    "label": label_text,
                    "field_type": field_type,
                    "locator": locator,
                    "required": True,  # LinkedIn typically marks all as required
                    "options": options,
                })

            except Exception as exc:
                print(f"    [linkedin] field extraction error: {exc}")
                continue

        print(f"    [linkedin] extracted {len(fields)} fields on this step")
        return fields

    async def _get_select_options_in(self, container) -> List[str]:
        try:
            options = await container.query_selector_all("option")
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
        """Click Next or Review button in the modal. Returns False if on Submit step."""
        try:
            # Check for Submit button first
            submit_btn = await self.page.query_selector(self.SUBMIT_BTN)
            if submit_btn:
                return False  # We're on the final step

            # Click Review or Next
            for selector in [self.REVIEW_BTN, self.NEXT_BTN]:
                btn = await self.page.query_selector(selector)
                if btn:
                    await btn.click()
                    await self.page.wait_for_load_state("networkidle", timeout=8_000)
                    return True

            return False
        except Exception:
            return False

    async def submit_application(self) -> bool:
        """Click the final Submit button in the Easy Apply modal."""
        try:
            btn = await self.page.wait_for_selector(self.SUBMIT_BTN, timeout=8_000)
            if not btn:
                print("    [linkedin] submit button not found")
                return False

            await btn.click()
            await self.page.wait_for_load_state("networkidle", timeout=15_000)

            confirmation = await self.page.query_selector(self.CONFIRMATION)
            if confirmation:
                print("    [linkedin] application submitted — confirmation detected")
                return True

            print("    [linkedin] submitted (confirmation not confirmed)")
            return True
        except Exception as exc:
            print(f"    [linkedin] submit failed: {exc}")
            return False
