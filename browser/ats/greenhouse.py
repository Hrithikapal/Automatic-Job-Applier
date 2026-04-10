"""
browser/ats/greenhouse.py — Greenhouse ATS handler.

Greenhouse uses standard HTML forms with stable id/name attributes.
The application form lives below the job listing on the same page
(job-boards.greenhouse.io/{company}/jobs/{id}) — clicking Apply
scrolls/navigates to the form.

Form structure (from DOM inspection):
  Standard section : First Name, Last Name, Email, Country (select), Phone
  Resume/CV        : hidden <input type="file" id="resume"> triggered by Attach btn
  Cover Letter     : hidden <input type="file" id="cover_letter">
  Custom questions : <input|textarea|select> with id="question_XXXXXXXX_N"
  EEO section      : selects for gender, hispanic_ethnicity, veteran_status,
                     disability_status (all voluntary)
"""
from __future__ import annotations

import os
import re
from typing import List

from browser.ats.base import BaseATSHandler
from browser.session import BrowserSession


class GreenhouseHandler(BaseATSHandler):

    # ------------------------------------------------------------------
    # Stable Greenhouse selectors
    # ------------------------------------------------------------------
    FORM_SELECTOR      = "#application_form, form.application, form[action*='applications'], main form, form"
    SUBMIT_BTN         = (
        "#submit_app, "
        "input[type='submit'][value*='Submit'], "
        "button[type='submit'], "
        "button:has-text('Submit application'), "
        "button:has-text('Submit'), "
        "input[type='submit']"
    )
    APPLY_BTN          = (
        "a#header_apply_button, "
        "a.apply-button, "
        "a[href*='applications/new'], "
        "a[href*='#app'], "
        ".apply-button a, "
        "button.apply-button, "
        ".btn-apply, "
        "button:has-text('Apply'), "
        "a:has-text('Apply Now'), "
        "a:has-text('Apply')"
    )
    RESUME_INPUT       = "input#resume, input[name='job_application[resume]']"
    COVER_LETTER_INPUT = "input#cover_letter, input[name='job_application[cover_letter]']"
    RESUME_ATTACH_BTN  = "#resume_trigger, button[aria-label*='Resume'], label[for='resume']"
    COVER_ATTACH_BTN   = "#cover_letter_trigger, button[aria-label*='Cover'], label[for='cover_letter']"

    CONFIRMATION_SELECTORS = [
        ".confirmation",
        ".thanks",
        "#confirmation",
        "[class*='confirmation']",
        "h1:has-text('Thank')",
        "h2:has-text('Thank')",
        ".submitted",
    ]

    # EEO select field IDs — keys are used verbatim as field labels so that
    # _normalise_label() in field_resolver produces the matching custom_answers key.
    EEO_SELECTS = {
        "Gender":              "#job_application_gender, select[name*='gender']",
        "Hispanic Ethnicity":  "#job_application_hispanic_ethnicity, select[name*='hispanic']",
        "Veteran Status":      "#job_application_veteran_status, select[name*='veteran']",
        "Disability Status":   "#job_application_disability_status, select[name*='disability']",
    }

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
        """Greenhouse public boards require no sign-in."""
        print("    [greenhouse] no sign-in required for public boards")
        return True

    # ------------------------------------------------------------------ #
    # Navigation                                                           #
    # ------------------------------------------------------------------ #

    async def navigate_to_apply(self, job_url: str) -> bool:
        """
        Navigate to the Greenhouse job listing then click Apply to reveal
        the application form (which is on the same page, below the listing).
        """
        try:
            await self.page.goto(job_url, wait_until="domcontentloaded", timeout=30_000)
            await self.page.wait_for_load_state("networkidle", timeout=15_000)

            # Click the Apply button if it exists.
            # On job-boards.greenhouse.io it navigates to /applications/new.
            apply_btn = await self.page.query_selector(self.APPLY_BTN)
            if apply_btn:
                try:
                    async with self.page.expect_navigation(timeout=10_000):
                        await apply_btn.click()
                    print("    [greenhouse] clicked Apply — navigated to application form")
                except Exception:
                    # No navigation (just scroll) — that's fine
                    await self.page.wait_for_load_state("networkidle", timeout=8_000)
                    print("    [greenhouse] clicked Apply button")

            # Wait for the application form to be present in the DOM
            try:
                await self.page.wait_for_selector(self.FORM_SELECTOR, timeout=10_000)
            except Exception:
                # Some Greenhouse boards embed the form directly — acceptable
                pass

            # Wait for inputs to render (new job-boards format can be slow)
            try:
                await self.page.wait_for_selector("input[type='text'], input[type='email']", timeout=8_000)
            except Exception:
                pass

            print("    [greenhouse] application form reached")
            return True
        except Exception as exc:
            print(f"    [greenhouse] navigation failed: {exc}")
            return False

    # ------------------------------------------------------------------ #
    # Form extraction                                                      #
    # ------------------------------------------------------------------ #

    async def extract_form_fields(self) -> List[dict]:
        """
        Extract every fillable field from the Greenhouse application form.

        Handles:
          • Standard text/email/tel/select inputs linked via <label for="id">
          • File inputs for Resume and Cover Letter
          • Custom questions (id pattern: question_NNNNN_N)
          • EEO voluntary self-identification selects
        """
        await self.page.wait_for_load_state("networkidle", timeout=10_000)

        fields: List[dict] = []
        seen_locators: set[str] = set()

        # ── 1. Standard fields via <label for="..."> ──────────────────────
        # Try specific Greenhouse form selectors first, fall back to full page
        labels = await self.page.query_selector_all(
            "#application_form label, .application--wrapper label"
        )
        if not labels:
            # New job-boards.greenhouse.io format — scan all labels on the page
            labels = await self.page.query_selector_all("label[for]")

        for label_el in labels:
            try:
                raw_text = (await label_el.inner_text()).strip()
                label_text = raw_text.replace("*", "").strip()
                if not label_text:
                    continue

                for_attr = await label_el.get_attribute("for")
                if not for_attr:
                    continue

                locator = f"#{for_attr}"
                if locator in seen_locators:
                    continue

                input_el = await self.page.query_selector(locator)
                if not input_el:
                    continue

                field_info = await self._classify_element(input_el, locator, label_text)
                if field_info:
                    seen_locators.add(locator)
                    fields.append(field_info)

            except Exception as exc:
                print(f"    [greenhouse] label scan error: {exc}")
                continue

        # ── 2. File inputs not covered by labels (resume / cover letter) ──
        for file_locator, file_label, required in [
            (self.RESUME_INPUT,       "Resume/CV",    True),
            (self.COVER_LETTER_INPUT, "Cover Letter", False),
        ]:
            el = await self.page.query_selector(file_locator)
            if el:
                # Use the first matching selector as the canonical locator
                canonical = file_locator.split(",")[0].strip()
                if canonical not in seen_locators:
                    seen_locators.add(canonical)
                    fields.append({
                        "label":      file_label,
                        "field_type": "file",
                        "locator":    canonical,
                        "required":   required,
                        "options":    [],
                    })

        # ── 3. EEO / Voluntary Self-Identification selects ────────────────
        for eeo_label, eeo_locator in self.EEO_SELECTS.items():
            if eeo_locator in seen_locators:
                continue
            el = await self.page.query_selector(eeo_locator)
            if el:
                options = await self._get_select_options(eeo_locator)
                seen_locators.add(eeo_locator)
                fields.append({
                    "label":      eeo_label,   # verbatim — normalises to the custom_answers key
                    "field_type": "select",
                    "locator":    eeo_locator,
                    "required":   False,
                    "options":    options,
                })

        # Sort fields by vertical DOM position so they are filled top-to-bottom
        # (file inputs added in step 2 may appear above text fields from step 1)
        positioned: list[tuple[float, int]] = []
        for i, field in enumerate(fields):
            try:
                el = await self.page.query_selector(field["locator"])
                box = await el.bounding_box() if el else None
                positioned.append((box["y"] if box else float("inf"), i))
            except Exception:
                positioned.append((float("inf"), i))
        positioned.sort()
        fields = [fields[i] for _, i in positioned]

        print(f"    [greenhouse] extracted {len(fields)} fields")
        return fields

    async def _classify_element(
        self, input_el, locator: str, label_text: str
    ) -> dict | None:
        """Return a field dict for the given element, or None to skip it."""
        try:
            tag        = await input_el.evaluate("el => el.tagName.toLowerCase()")
            input_type = (await input_el.get_attribute("type") or "text").lower()

            # Skip hidden, submit, and button inputs
            if input_type in ("hidden", "submit", "button", "image", "reset"):
                return None

            # Determine field_type
            if tag == "select":
                field_type = "select"
                options    = await self._get_select_options(locator)
            elif tag == "textarea":
                field_type = "textarea"
                options    = []
            elif input_type == "file":
                field_type = "file"
                options    = []
            elif input_type == "checkbox":
                field_type = "checkbox"
                options    = []
            elif input_type == "radio":
                field_type = "radio"
                options    = []
            else:
                field_type = "text"
                options    = []

            required = (
                await input_el.get_attribute("required") is not None
                or await input_el.get_attribute("aria-required") == "true"
            )

            return {
                "label":      label_text,
                "field_type": field_type,
                "locator":    locator,
                "required":   required,
                "options":    options,
            }
        except Exception:
            return None

    async def _get_select_options(self, locator: str) -> List[str]:
        """Return non-empty option labels for a <select> element."""
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
        """
        Fill a single field.

        For file inputs Greenhouse hides the <input type='file'> behind an
        'Attach' button — we set_input_files directly on the hidden input,
        which Playwright supports without needing to click the button first.

        For text-like inputs, types the value then checks for an autocomplete
        dropdown (e.g. the Country/phone-code picker) and clicks the best
        matching option if one appears.
        """
        if field_type == "file":
            return await self._fill_file(locator, value)
        if field_type == "select":
            return await self._fill_select(locator, value)
        # Text-like fields: type + handle autocomplete dropdown
        return await self._fill_with_autocomplete(locator, value, field_type)

    async def _fill_with_autocomplete(
        self, locator: str, value: str, field_type: str
    ) -> bool:
        """
        Type into a field, then detect any dropdown that appears and
        select the best matching option.

        Strategy:
          1. Type the value character-by-character
          2. Use JS to find visible elements BELOW the input that look
             like dropdown options (position-based, no CSS selector guessing)
          3. If JS click works → done
          4. If not → use keyboard (ArrowDown + Enter) as universal fallback
        """
        try:
            # Clear and type character-by-character to trigger autocomplete JS
            await self.page.fill(locator, "")
            await self.page.type(locator, value, delay=50)

            # Wait for dropdown to render
            await self.page.wait_for_timeout(800)

            # Get input element position to find elements below it
            input_box = await self.page.locator(locator).bounding_box()
            if not input_box:
                return True

            input_bottom = input_box["y"] + input_box["height"]

            # --- Approach 1: JS position-based detection ---
            # Find small visible elements BELOW the input with matching text.
            # Does not rely on any CSS class, ARIA role, or positioning method.
            result = await self.page.evaluate("""(args) => {
                const { value, inputBottom } = args;
                const valueLower = value.toLowerCase();

                const all = document.querySelectorAll('div, li, span, a, option, [role="option"]');
                let startsMatch = null;
                let containsMatch = null;
                let firstBelow = null;

                for (const el of all) {
                    const tag = el.tagName.toLowerCase();
                    if (['input','textarea','label','form','body','html','script','style','h1','h2','h3','h4','select'].includes(tag))
                        continue;

                    const rect = el.getBoundingClientRect();
                    if (rect.width < 20 || rect.height < 10) continue;
                    // Must be below or near the bottom edge of the input
                    if (rect.top < inputBottom - 5) continue;
                    // Must be within reasonable range below
                    if (rect.top > inputBottom + 400) continue;
                    // Must be small-ish (not a large container)
                    if (rect.height > 200) continue;

                    const style = window.getComputedStyle(el);
                    if (style.display === 'none' || style.visibility === 'hidden') continue;

                    const text = (el.innerText || '').trim();
                    if (!text || text.length > 500) continue;

                    if (!firstBelow) firstBelow = { el, text };

                    const clean = text.replace(/^[^a-zA-Z0-9]+/, '').trim();
                    if (!startsMatch && clean.toLowerCase().startsWith(valueLower)) {
                        startsMatch = { el, text };
                    }
                    if (!containsMatch && text.toLowerCase().includes(valueLower)) {
                        containsMatch = { el, text };
                    }
                }

                const pick = startsMatch || containsMatch || firstBelow;
                if (pick) {
                    pick.el.click();
                    return { clicked: true, text: pick.text.substring(0, 80), hasDropdown: true };
                }
                return { clicked: false, hasDropdown: firstBelow !== null };
            }""", {"value": value, "inputBottom": input_bottom})

            if result and result.get("clicked"):
                print(f"    [greenhouse] selected dropdown option: {result.get('text', '')}")
                await self.page.wait_for_timeout(200)
                return True

            # --- Approach 2: Keyboard ArrowDown + Enter ---
            # Universal fallback — works with any dropdown/combobox that
            # handles keyboard navigation (virtually all of them).
            # Temporarily block form submission so Enter doesn't submit.
            if result and result.get("hasDropdown"):
                await self.page.evaluate("""() => {
                    window.__blockSubmit = e => { e.preventDefault(); e.stopPropagation(); };
                    document.querySelectorAll('form').forEach(
                        f => f.addEventListener('submit', window.__blockSubmit, true)
                    );
                }""")
                try:
                    await self.page.keyboard.press("ArrowDown")
                    await self.page.wait_for_timeout(150)
                    await self.page.keyboard.press("Enter")
                    await self.page.wait_for_timeout(150)
                    print(f"    [greenhouse] selected dropdown via keyboard for '{value}'")
                finally:
                    await self.page.evaluate("""() => {
                        if (window.__blockSubmit) {
                            document.querySelectorAll('form').forEach(
                                f => f.removeEventListener('submit', window.__blockSubmit, true)
                            );
                            delete window.__blockSubmit;
                        }
                    }""")
                return True

            # No dropdown appeared — the typed text is the final value
            return True
        except Exception as exc:
            print(f"    [greenhouse] autocomplete fill failed for {locator!r}: {exc}")
            try:
                await self.page.evaluate("""() => {
                    if (window.__blockSubmit) {
                        document.querySelectorAll('form').forEach(
                            f => f.removeEventListener('submit', window.__blockSubmit, true)
                        );
                        delete window.__blockSubmit;
                    }
                }""")
            except Exception:
                pass
            return await self.fill_field_generic(locator, value, field_type)

    async def _fill_select(self, locator: str, value: str) -> bool:
        """
        Fill a <select> with fuzzy matching.

        1. Try exact label match
        2. Try exact value match
        3. Try partial/fuzzy match (option contains value or vice versa)
        4. Fallback: select the first non-empty option
        """
        try:
            # 1. Exact label match
            try:
                await self.page.select_option(locator, label=value)
                return True
            except Exception:
                pass
            # 2. Exact value match
            try:
                await self.page.select_option(locator, value=value)
                return True
            except Exception:
                pass

            # 3. Fuzzy match — option text contains the value or vice versa
            options = await self.page.query_selector_all(f"{locator} option")
            value_lower = value.lower()
            first_valid_value = None
            first_valid_text = None
            for opt in options:
                opt_value = (await opt.get_attribute("value") or "").strip()
                if not opt_value:
                    continue
                text = (await opt.inner_text()).strip()
                if first_valid_value is None:
                    first_valid_value = opt_value
                    first_valid_text = text
                if value_lower in text.lower() or text.lower() in value_lower:
                    await self.page.select_option(locator, value=opt_value)
                    print(f"    [greenhouse] fuzzy-matched select option: {text}")
                    return True

            # 4. No match at all — select the first non-empty option
            if first_valid_value:
                await self.page.select_option(locator, value=first_valid_value)
                print(f"    [greenhouse] fallback: selected first option: {first_valid_text}")
                return True

            return False
        except Exception as exc:
            print(f"    [greenhouse] select fill failed for {locator!r}: {exc}")
            return False

    async def _fill_file(self, locator: str, file_path: str) -> bool:
        """Upload a file to a (possibly hidden) Greenhouse file input."""
        if not file_path or not os.path.exists(file_path):
            print(f"    [greenhouse] file not found: {file_path!r}")
            return False
        try:
            # Playwright can set_input_files on hidden inputs directly
            await self.page.set_input_files(locator, file_path)
            print(f"    [greenhouse] uploaded {os.path.basename(file_path)} → {locator}")
            return True
        except Exception as exc:
            print(f"    [greenhouse] file upload failed for {locator!r}: {exc}")
            return False

    # ------------------------------------------------------------------ #
    # Navigation helpers                                                   #
    # ------------------------------------------------------------------ #

    async def next_section(self) -> bool:
        """
        Greenhouse applications are single-page — no Next button.
        Returns None so the pipeline knows there is no next section
        and proceeds to submit (False would mean validation error).
        """
        return None

    async def submit_application(self) -> bool:
        """Click Submit and verify a confirmation element or URL change."""
        try:
            btn = await self.page.query_selector(self.SUBMIT_BTN)
            if not btn:
                print("    [greenhouse] submit button not found")
                return False

            await btn.click()
            await self.page.wait_for_load_state("networkidle", timeout=20_000)

            # Check DOM for confirmation indicators
            for selector in self.CONFIRMATION_SELECTORS:
                try:
                    el = await self.page.query_selector(selector)
                    if el:
                        print("    [greenhouse] application submitted — confirmation detected")
                        return True
                except Exception:
                    pass

            # URL-based fallback: Greenhouse redirects to /confirmation after submit
            if "confirmation" in self.page.url or "thank" in self.page.url.lower():
                print("    [greenhouse] application submitted — confirmation URL detected")
                return True

            print("    [greenhouse] submitted (no explicit confirmation found)")
            return True
        except Exception as exc:
            print(f"    [greenhouse] submit failed: {exc}")
            return False
