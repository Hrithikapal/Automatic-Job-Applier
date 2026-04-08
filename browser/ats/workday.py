"""
browser/ats/workday.py — Workday ATS handler.

Workday uses data-automation-id attributes on every interactive element,
making it the most automation-friendly platform when you know the selectors.

Application flow (per screenshots):
  1. Job page  → click Apply → "Start Your Application" modal
  2. Modal     → click "Autofill with Resume"
  3. Redirect  → Sign In page (sign in with email)
  4. Signed in → Autofill with Resume page (file upload)
  5. Upload PDF → click Continue → wizard sections:
     My Information → My Experience → Application Questions →
     Voluntary Disclosures → Review → Submit
"""
from __future__ import annotations

import os
from typing import List

from browser.ats.base import BaseATSHandler
from browser.session import BrowserSession


class WorkdayHandler(BaseATSHandler):

    # ── Stable automation selectors ──────────────────────────────────────
    FIELD_CONTAINER   = "[data-automation-id='formField']"
    NEXT_BTN          = "[data-automation-id='bottom-navigation-next-button']"
    SUBMIT_BTN        = "[data-automation-id='bottom-navigation-footer-button']"
    APPLY_BTN         = "[data-automation-id='applyButton']"
    # Sign-in page selectors (after "Sign in with email" is clicked)
    SIGNIN_EMAIL_BTN  = "button:has-text('Sign in with email')"
    LOGIN_EMAIL       = "[data-automation-id='email']"
    LOGIN_PASSWORD    = "[data-automation-id='password']"
    LOGIN_SUBMIT      = "[data-automation-id='signInSubmitButton']"
    # "Start Your Application" modal
    AUTOFILL_BTN      = "button:has-text('Autofill with Resume')"
    # Resume upload page
    FILE_INPUT        = "input[type='file']"
    CONTINUE_BTN      = "[data-automation-id='bottom-navigation-next-button']"
    CONFIRMATION      = "[data-automation-id='thankYouPage']"

    def __init__(self, session: BrowserSession):
        super().__init__(session)
        self._email: str = ""
        self._password: str = ""

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
        """
        Store credentials for later use in navigate_to_apply.
        Workday redirects to sign-in AFTER you click "Autofill with Resume",
        so we defer the actual sign-in to _handle_sign_in_if_needed().
        """
        self._email = email
        self._password = password
        print("    [workday] credentials stored — will sign in when redirected")
        return True

    async def _handle_sign_in_if_needed(self) -> None:
        """Sign in if the current page is a Workday sign-in page."""
        try:
            # Detect sign-in page by presence of sign-in options
            email_btn = await self.page.query_selector(self.SIGNIN_EMAIL_BTN)
            if not email_btn:
                return  # Already signed in or no sign-in page

            if not self._email or not self._password:
                print("    [workday] sign-in page detected but no credentials provided — skipping")
                return

            # Click "Sign in with email"
            await email_btn.click()
            await self.page.wait_for_load_state("networkidle", timeout=8_000)

            # Fill email and password
            await self.page.wait_for_selector(self.LOGIN_EMAIL, timeout=8_000)
            await self.page.fill(self.LOGIN_EMAIL, self._email)
            await self.page.fill(self.LOGIN_PASSWORD, self._password)
            await self.page.click(self.LOGIN_SUBMIT)
            await self.page.wait_for_load_state("networkidle", timeout=12_000)
            print("    [workday] signed in via email")

        except Exception as exc:
            print(f"    [workday] sign-in handling failed: {exc}")

    # ------------------------------------------------------------------ #
    # Navigation                                                           #
    # ------------------------------------------------------------------ #

    async def navigate_to_apply(self, job_url: str) -> bool:
        """
        Full Workday apply flow:
          1. Navigate to job page
          2. Click Apply → handle "Start Your Application" modal
          3. Click "Autofill with Resume"
          4. Handle sign-in redirect if needed
          5. Upload resume PDF
          6. Click Continue into the form wizard
        """
        try:
            await self.page.goto(job_url, wait_until="networkidle", timeout=30_000)

            # Step 1 — Click Apply
            apply_btn = await self.page.query_selector(self.APPLY_BTN)
            if apply_btn:
                await apply_btn.click()
                await self.page.wait_for_load_state("networkidle", timeout=10_000)
                print("    [workday] clicked Apply button")

            # Step 2 — Handle "Start Your Application" modal
            # Click "Autofill with Resume"
            try:
                autofill_btn = await self.page.wait_for_selector(
                    self.AUTOFILL_BTN, timeout=8_000
                )
                await autofill_btn.click()
                await self.page.wait_for_load_state("networkidle", timeout=15_000)
                print("    [workday] clicked Autofill with Resume")
            except Exception:
                print("    [workday] no application modal found — continuing")

            # Step 3 — Sign in if redirected to login page
            await self._handle_sign_in_if_needed()

            # Step 4 — Upload resume on the Autofill page
            await self._upload_resume()

            # Step 5 — Click Continue into wizard
            try:
                continue_btn = await self.page.wait_for_selector(
                    self.CONTINUE_BTN, timeout=8_000
                )
                await continue_btn.click()
                await self.page.wait_for_load_state("networkidle", timeout=15_000)
                print("    [workday] clicked Continue — entering form wizard")
            except Exception:
                print("    [workday] Continue button not found — may already be in wizard")

            print("    [workday] navigated to application form")
            return True

        except Exception as exc:
            print(f"    [workday] navigation failed: {exc}")
            return False

    async def _upload_resume(self) -> None:
        """Upload the candidate resume PDF on the Autofill with Resume page."""
        try:
            file_input = await self.page.query_selector(self.FILE_INPUT)
            if not file_input:
                print("    [workday] no file input found on autofill page — skipping upload")
                return

            # Resolve resume path from candidate profile or env
            resume_path = os.getenv("RESUME_PATH", "assets/resumes/alex_chen_resume.pdf")
            if not os.path.exists(resume_path):
                print(f"    [workday] resume not found at {resume_path} — skipping upload")
                return

            await file_input.set_input_files(resume_path)
            await self.page.wait_for_load_state("networkidle", timeout=10_000)
            print(f"    [workday] uploaded resume: {resume_path}")

        except Exception as exc:
            print(f"    [workday] resume upload failed: {exc}")

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
                options = []

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
                    for r in radios:
                        val = await r.get_attribute("value") or ""
                        if val:
                            options.append(val)

                # Check for checkbox
                if not locator:
                    checkbox = await container.query_selector("input[type='checkbox']")
                    if checkbox:
                        field_type = "checkbox"
                        automation_id = await checkbox.get_attribute("data-automation-id")
                        locator = f"[data-automation-id='{automation_id}']" if automation_id else None

                # Check for textarea
                if not locator:
                    textarea = await container.query_selector("textarea")
                    if textarea:
                        field_type = "textarea"
                        automation_id = await textarea.get_attribute("data-automation-id")
                        locator = f"[data-automation-id='{automation_id}']" if automation_id else None

                # Check for file input
                if not locator:
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
                    "options": options,
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
    # Wizard navigation                                                    #
    # ------------------------------------------------------------------ #

    async def next_section(self) -> bool:
        """Click Save and Continue / Next. Returns False if no next button."""
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
