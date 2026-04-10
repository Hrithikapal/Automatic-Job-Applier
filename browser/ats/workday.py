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
            # Check for direct email field (sign-in page without intermediate button)
            email_field = await self.page.query_selector(self.LOGIN_EMAIL)

            if not email_field:
                # Check for "Sign in with email" button (some Workday variants)
                email_btn = await self.page.query_selector(self.SIGNIN_EMAIL_BTN)
                if email_btn:
                    await email_btn.click()
                    await self.page.wait_for_load_state("domcontentloaded", timeout=8_000)
                    email_field = await self.page.wait_for_selector(
                        self.LOGIN_EMAIL, timeout=8_000
                    )
                else:
                    return  # Not a sign-in page

            if not self._email or not self._password:
                print("    [workday] sign-in page detected but no credentials provided — skipping")
                return

            # Fill email and password
            await email_field.fill(self._email)
            await self.page.fill(self.LOGIN_PASSWORD, self._password)
            print("    [workday] filled email and password")

            # Click sign-in button — try multiple methods to bypass overlays
            submit_btn = await self.page.wait_for_selector(
                self.LOGIN_SUBMIT, timeout=8_000
            )
            try:
                # Try force click first (bypasses pointer-intercepting overlays)
                await submit_btn.click(force=True)
            except Exception:
                # Fallback: dispatch event directly on the element
                await self.page.evaluate(
                    """() => {
                        const btn = document.querySelector('[data-automation-id="signInSubmitButton"]');
                        if (btn) btn.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                    }"""
                )
            await self.page.wait_for_load_state("domcontentloaded", timeout=15_000)
            print("    [workday] signed in successfully")

        except Exception as exc:
            print(f"    [workday] sign-in handling failed: {exc}")

    # ------------------------------------------------------------------ #
    # Navigation                                                           #
    # ------------------------------------------------------------------ #

    async def navigate_to_apply(self, job_url: str) -> bool:
        """
        Full Workday apply flow (Apply Manually path):
          1. Navigate to job page (skip if already there)
          2. Click Apply → "Start Your Application" modal
          3. Click "Apply Manually" — goes directly to the form wizard
          4. Handle sign-in redirect if needed
          5. Wait for the first wizard section (My Information) to load
        """
        try:
            # Skip navigation if already on the job page (browser_init loaded it)
            current = self.page.url
            if job_url not in current and current not in job_url:
                await self.page.goto(job_url, wait_until="networkidle", timeout=30_000)

            # Step 1 — Find and click Apply button.
            # Race all selectors in parallel so we don't burn up to 10s per
            # selector sequentially. First one to resolve wins.
            import asyncio as _asyncio

            APPLY_SELECTORS = [
                "[data-automation-id='applyButton']",
                "button:has-text('Apply')",
                "a:has-text('Apply')",
            ]

            async def _try_selector(sel: str):
                el = await self.page.wait_for_selector(sel, timeout=10_000)
                return sel, el

            apply_btn = None
            apply_sel = None
            try:
                tasks = [_asyncio.ensure_future(_try_selector(s)) for s in APPLY_SELECTORS]
                done, pending = await _asyncio.wait(
                    tasks, return_when=_asyncio.FIRST_COMPLETED
                )
                for t in pending:
                    t.cancel()
                apply_sel, apply_btn = next(iter(done)).result()
                print(f"    [workday] found Apply button via: {apply_sel}")
            except Exception:
                apply_btn = None

            if not apply_btn:
                print("    [workday] Apply button not found — cannot proceed")
                return False

            await apply_btn.click()
            print("    [workday] clicked Apply button — waiting for modal")

            # Step 2 — Wait for the modal and click a button inside it.
            # Workday renders the modal in shadow DOM, so standard CSS :has-text()
            # selectors used with query_selector cannot reach it. Use Playwright's
            # Locator API (get_by_role / get_by_text) which traverses shadow roots.
            try:
                # Brief pause for the modal animation to complete
                await self.page.wait_for_timeout(2_000)

                clicked = False
                # Priority order: Apply Manually first (fills from profile, not resume parse)
                MANUAL_NAMES  = ["Apply Manually", "Fill Out Manually"]
                FALLBACK_NAMES = ["Autofill with Resume", "Continue", "Use My Last Application"]

                for name in MANUAL_NAMES + FALLBACK_NAMES:
                    try:
                        btn = self.page.get_by_role("button", name=name, exact=False)
                        await btn.click(timeout=5_000)
                        await self.page.wait_for_load_state("networkidle", timeout=20_000)
                        print(f"    [workday] clicked modal button: '{name}'")
                        clicked = True
                        break
                    except Exception:
                        continue

                if not clicked:
                    print("    [workday] no modal button found — may have navigated directly or modal uses unknown labels")

            except Exception as exc:
                print(f"    [workday] modal handling failed: {exc}")

            # Step 3 — Sign in if redirected to login page
            await self._handle_sign_in_if_needed()

            # Step 4 — Detect and recover from "Something went wrong" page.
            # Poll every 300 ms (up to 6 s first attempt, 3 s on retries).
            # Break immediately on crash detection or when form fields are visible.
            for _attempt in range(3):
                poll_iters = 20 if _attempt == 0 else 10   # × 300 ms = 6 s / 3 s
                page_text = ""
                crashed = False
                for _ in range(poll_iters):
                    await self.page.wait_for_timeout(300)
                    try:
                        page_text = await self.page.evaluate(
                            "() => document.documentElement.innerText"
                        )
                    except Exception:
                        page_text = ""
                    if "something went wrong" in (page_text or "").lower():
                        crashed = True
                        break   # crash confirmed — reload immediately, don't wait
                    # Page is healthy — exit as soon as form elements are visible
                    try:
                        has_form = await self.page.query_selector(
                            "[data-automation-id='formField'], input[type='text']"
                        )
                        if has_form:
                            break
                    except Exception:
                        break

                if not crashed:
                    break  # page healthy — stop reload loop

                print(f"    [workday] 'Something went wrong' detected (attempt {_attempt+1}) — reloading")
                await self.page.reload(wait_until="domcontentloaded", timeout=20_000)
                await self.page.wait_for_timeout(500)

            # Step 5 — Wait for the first wizard section to load.
            # Use a broad set of selectors since data-automation-id='formField' is
            # not always present on every Workday tenant / section.
            print("    [workday] waiting for form wizard (My Information) to load...")
            WIZARD_READY_SELECTORS = [
                "[data-automation-id='formField']",
                "[data-automation-id='radioGroup']",
                "input[type='text']",
                "select",
            ]
            wizard_loaded = False
            for sel in WIZARD_READY_SELECTORS:
                try:
                    await self.page.wait_for_selector(sel, timeout=8_000)
                    wizard_loaded = True
                    print(f"    [workday] wizard loaded (detected via: {sel})")
                    break
                except Exception:
                    continue
            if not wizard_loaded:
                print(f"    [workday] wizard load timed out (url: {self.page.url}) — proceeding anyway")

            print("    [workday] navigated to application form")
            return True

        except Exception as exc:
            print(f"    [workday] navigation failed: {exc}")
            return False

    async def _upload_resume(self, resume_path: str | None = None) -> None:
        """Upload the candidate resume PDF on the Autofill with Resume page."""
        try:
            # Wait for the autofill page to fully settle after sign-in redirect.
            # Use state='attached' because Workday's file input is hidden under
            # the styled drop zone — it's never 'visible', but it IS in the DOM.
            print("    [workday] waiting for file input on autofill page...")
            try:
                file_input = await self.page.wait_for_selector(
                    self.FILE_INPUT, timeout=15_000, state="attached"
                )
            except Exception:
                print("    [workday] no file input found on autofill page — skipping upload")
                return

            if not file_input:
                print("    [workday] file input resolved to None — skipping upload")
                return

            # Resolve resume path: caller → env var → default
            if not resume_path:
                resume_path = os.getenv("RESUME_PATH", "assets/resumes/hrithika_pal_resume.pdf")
            if not os.path.exists(resume_path):
                print(f"    [workday] resume not found at {resume_path} — skipping upload")
                return

            await file_input.set_input_files(resume_path)
            # Wait for Workday to process the upload (it shows a spinner)
            try:
                await self.page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass  # proceed even if networkidle times out
            print(f"    [workday] uploaded resume: {resume_path}")

        except Exception as exc:
            print(f"    [workday] resume upload failed: {exc}")

    # ------------------------------------------------------------------ #
    # Form extraction                                                      #
    # ------------------------------------------------------------------ #

    async def extract_form_fields(self) -> List[dict]:
        """
        Scan the current wizard page for all form fields.

        Strategy:
          1. Collect containers from multiple data-automation-id patterns
             (formField, radioGroup, checkboxPanel) — Workday uses all of them.
          2. Inside each container, detect field type and build a stable locator.
          3. Deduplicate by locator to avoid double-reporting shared inputs.
        """
        # Let JS finish rendering (networkidle can hang on Workday's long-poll XHRs)
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=8_000)
            await self.page.wait_for_timeout(600)
        except Exception:
            pass

        # Gather all field containers — Workday uses several automation IDs
        all_containers = []
        for sel in [
            "[data-automation-id='formField']",
            "[data-automation-id='radioGroup']",
            "[data-automation-id='checkboxPanel']",
        ]:
            found = await self.page.query_selector_all(sel)
            all_containers.extend(found)

        fields: list = []
        seen_locators: set = set()

        for container in all_containers:
            try:
                # ── Label ─────────────────────────────────────────────────
                label_el = await container.query_selector(
                    "label, legend, [data-automation-id='formLabel']"
                )
                label = (await label_el.inner_text()).strip() if label_el else ""
                if not label:
                    continue
                # Strip trailing required asterisk
                label = label.rstrip(" *").strip()

                field_type = "text"
                locator: str | None = None
                options: list = []

                # ── Workday searchBox / combobox (e.g. "How Did You Hear", phone country code) ──
                searchbox = await container.query_selector(
                    "[data-automation-id='searchBox'], "
                    "[data-automation-id='multiselectInputContainer'] input, "
                    "[role='combobox'], "
                    "[data-uxi-widget-type='selectinput']"
                )
                if searchbox:
                    field_type = "workday_searchbox"
                    auto_id = await searchbox.get_attribute("data-automation-id")
                    sb_id   = await searchbox.get_attribute("id")
                    if auto_id:
                        locator = f"[data-automation-id='{auto_id}']"
                    elif sb_id:
                        locator = f"#{sb_id}"
                    else:
                        # Use parent container's automation-id as anchor
                        parent_id = await container.get_attribute("data-automation-id")
                        locator = f"[data-automation-id='{parent_id}'] input" if parent_id else None

                # ── Native <select> (e.g. Country / Territory, Phone Device Type) ──
                if not locator:
                    native_select = await container.query_selector("select")
                    if native_select:
                        field_type = "select"
                        sel_id = await native_select.get_attribute("id")
                        sel_name = await native_select.get_attribute("name")
                        sel_auto = await native_select.get_attribute("data-automation-id")
                        if sel_auto:
                            locator = f"select[data-automation-id='{sel_auto}']"
                        elif sel_id:
                            locator = f"select#{sel_id}"
                        elif sel_name:
                            locator = f"select[name='{sel_name}']"
                        else:
                            locator = "select"
                        option_els = await native_select.query_selector_all("option")
                        for opt in option_els:
                            val = (await opt.inner_text()).strip()
                            if val and val.lower() not in ("select one", "-- select --", ""):
                                options.append(val)

                # ── Radio group ─────────────────────────────────────────────
                if not locator:
                    radios = await container.query_selector_all("input[type='radio']")
                    if radios:
                        field_type = "radio"
                        # Collect human-readable labels for each radio button
                        for r in radios:
                            rid = await r.get_attribute("id")
                            lbl_el = await container.query_selector(
                                f"label[for='{rid}']"
                            ) if rid else None
                            if lbl_el:
                                opt_text = (await lbl_el.inner_text()).strip()
                            else:
                                opt_text = await r.get_attribute("value") or ""
                            if opt_text:
                                options.append(opt_text)
                        radio_name = await radios[0].get_attribute("name")
                        locator = f"input[name='{radio_name}']" if radio_name else None

                # ── Checkbox ────────────────────────────────────────────────
                if not locator:
                    checkbox = await container.query_selector("input[type='checkbox']")
                    if checkbox:
                        field_type = "checkbox"
                        auto_id = await checkbox.get_attribute("data-automation-id")
                        locator = f"[data-automation-id='{auto_id}']" if auto_id else None

                # ── Textarea ────────────────────────────────────────────────
                if not locator:
                    textarea = await container.query_selector("textarea")
                    if textarea:
                        field_type = "textarea"
                        auto_id = await textarea.get_attribute("data-automation-id")
                        locator = f"[data-automation-id='{auto_id}']" if auto_id else None

                # ── File input ──────────────────────────────────────────────
                if not locator:
                    file_input = await container.query_selector("input[type='file']")
                    if file_input:
                        field_type = "file"
                        locator = "input[type='file']"

                # ── Plain text / tel / email input ──────────────────────────
                if not locator:
                    text_input = await container.query_selector(
                        "input[type='text'], input[type='tel'], "
                        "input[type='email'], input:not([type])"
                    )
                    if text_input:
                        auto_id = await text_input.get_attribute("data-automation-id")
                        inp_name = await text_input.get_attribute("name")
                        inp_id   = await text_input.get_attribute("id")
                        if auto_id:
                            locator = f"[data-automation-id='{auto_id}']"
                        elif inp_id:
                            locator = f"input#{inp_id}"
                        elif inp_name:
                            locator = f"input[name='{inp_name}']"

                if not locator or locator in seen_locators:
                    continue
                seen_locators.add(locator)

                required_attr = await container.get_attribute("aria-required")
                required = required_attr == "true"

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

        # ── Fallback: broad scan when container selectors matched nothing ──────
        # Some Workday tenants / sections don't use the standard automation IDs.
        # In that case walk all visible inputs and match them to their nearest label.
        if not fields:
            print("    [workday] container scan found 0 fields — falling back to broad input scan")
            fields = await self._extract_fields_broad()

        print(f"    [workday] extracted {len(fields)} fields")
        return fields

    async def _extract_fields_broad(self) -> list:
        """
        Fallback extractor: walk every visible input/select/textarea on the page
        and pair it with its label by (1) for= attribute, (2) aria-label,
        (3) placeholder, (4) nearest preceding <label> in the DOM.
        """
        fields: list = []
        seen_locators: set = set()

        # Collect every interactive element
        INPUT_SEL = (
            "input[type='text'], input[type='tel'], input[type='email'], "
            "input[type='number'], input:not([type]), "
            "select, textarea"
        )
        inputs = await self.page.query_selector_all(INPUT_SEL)

        for inp in inputs:
            try:
                # Skip hidden / file inputs
                inp_type = (await inp.get_attribute("type") or "").lower()
                if inp_type in ("hidden", "file", "submit", "button"):
                    continue
                visible = await inp.is_visible()
                if not visible:
                    continue

                # Build stable locator
                auto_id  = await inp.get_attribute("data-automation-id")
                inp_id   = await inp.get_attribute("id")
                inp_name = await inp.get_attribute("name")
                if auto_id:
                    locator = f"[data-automation-id='{auto_id}']"
                elif inp_id:
                    locator = f"#{inp_id}"
                elif inp_name:
                    locator = f"[name='{inp_name}']"
                else:
                    continue   # no stable handle

                if locator in seen_locators:
                    continue

                # Workday selectinput widgets — classify as workday_searchbox
                # right here so they appear in DOM order alongside text inputs.
                # (Do NOT defer to the second loop — that would put them at the
                # end of the list, causing country-code to fill after phone-number
                # which makes Workday reset the phone number → validation error.)
                uxi_type = await inp.get_attribute("data-uxi-widget-type")
                if uxi_type == "selectinput":
                    sb_label = ""
                    if inp_id:
                        lbl_el = await self.page.query_selector(f"label[for='{inp_id}']")
                        if lbl_el:
                            sb_label = (await lbl_el.inner_text()).strip().rstrip(" *").strip()
                    if not sb_label:
                        sb_label = (await inp.get_attribute("aria-label") or "").strip()
                    if not sb_label:
                        sb_label = await self.page.evaluate(
                            """(el) => {
                                let p = el.parentElement;
                                for (let i = 0; i < 5; i++) {
                                    if (!p) break;
                                    const lbl = p.querySelector('label');
                                    if (lbl) return lbl.innerText.trim();
                                    p = p.parentElement;
                                }
                                return '';
                            }""",
                            inp,
                        )
                        sb_label = (sb_label or "").rstrip(" *").strip()
                    if not sb_label:
                        continue
                    seen_locators.add(locator)
                    req_attr = await inp.get_attribute("required")
                    aria_req = await inp.get_attribute("aria-required")
                    fields.append({
                        "label": sb_label,
                        "field_type": "workday_searchbox",
                        "locator": locator,
                        "required": req_attr is not None or aria_req == "true",
                        "options": [],
                    })
                    continue

                seen_locators.add(locator)

                # Determine label
                label = ""
                if inp_id:
                    lbl = await self.page.query_selector(f"label[for='{inp_id}']")
                    if lbl:
                        label = (await lbl.inner_text()).strip().rstrip(" *").strip()
                if not label:
                    label = (await inp.get_attribute("aria-label") or "").strip()
                if not label:
                    label = (await inp.get_attribute("placeholder") or "").strip()
                if not label:
                    # Try evaluating to find the closest preceding label in the DOM
                    label = await self.page.evaluate(
                        """(el) => {
                            let node = el.previousElementSibling;
                            while (node) {
                                if (node.tagName === 'LABEL') return node.innerText.trim();
                                node = node.previousElementSibling;
                            }
                            const parent = el.parentElement;
                            if (parent) {
                                const lbl = parent.querySelector('label');
                                if (lbl) return lbl.innerText.trim();
                            }
                            return '';
                        }""",
                        inp,
                    )
                    label = (label or "").rstrip(" *").strip()

                if not label:
                    continue

                # Determine field type and options
                tag = (await inp.evaluate("el => el.tagName")).lower()
                field_type = "text"
                options: list = []

                if tag == "select":
                    field_type = "select"
                    opt_els = await inp.query_selector_all("option")
                    for opt in opt_els:
                        val = (await opt.inner_text()).strip()
                        if val and val.lower() not in ("select one", "-- select --", ""):
                            options.append(val)
                elif tag == "textarea":
                    field_type = "textarea"
                elif inp_type == "radio":
                    field_type = "radio"
                elif inp_type == "checkbox":
                    field_type = "checkbox"

                required_attr = await inp.get_attribute("required")
                aria_req = await inp.get_attribute("aria-required")
                required = required_attr is not None or aria_req == "true"

                fields.append({
                    "label": label,
                    "field_type": field_type,
                    "locator": locator,
                    "required": required,
                    "options": options,
                })

            except Exception as exc:
                print(f"    [workday] broad scan error: {exc}")
                continue

        # Also pick up Workday searchbox widgets (tag inputs like Country Phone Code)
        searchboxes = await self.page.query_selector_all(
            "[data-automation-id='searchBox'], "
            "[data-automation-id='multiselectInputContainer'] input, "
            "[data-uxi-widget-type='selectinput']"
        )
        for sb in searchboxes:
            try:
                visible = await sb.is_visible()
                if not visible:
                    continue
                auto_id = await sb.get_attribute("data-automation-id")
                inp_id  = await sb.get_attribute("id")
                locator = (
                    f"[data-automation-id='{auto_id}']" if auto_id
                    else f"#{inp_id}" if inp_id
                    else None
                )
                if not locator or locator in seen_locators:
                    continue
                seen_locators.add(locator)

                label = ""
                if inp_id:
                    lbl = await self.page.query_selector(f"label[for='{inp_id}']")
                    if lbl:
                        label = (await lbl.inner_text()).strip().rstrip(" *").strip()
                if not label:
                    label = (await sb.get_attribute("aria-label") or "").strip()
                if not label:
                    label = await self.page.evaluate(
                        """(el) => {
                            let p = el.parentElement;
                            for (let i = 0; i < 5; i++) {
                                if (!p) break;
                                const lbl = p.querySelector('label');
                                if (lbl) return lbl.innerText.trim();
                                p = p.parentElement;
                            }
                            return '';
                        }""",
                        sb,
                    )
                    label = (label or "").rstrip(" *").strip()

                if not label:
                    continue

                fields.append({
                    "label": label,
                    "field_type": "workday_searchbox",
                    "locator": locator,
                    "required": False,
                    "options": [],
                })
            except Exception:
                continue

        return fields

    # ------------------------------------------------------------------ #
    # Fill                                                                 #
    # ------------------------------------------------------------------ #

    async def fill_field(self, locator: str, value: str, field_type: str) -> bool:
        """Fill a field. Handles Workday-specific searchbox, radio, and native select."""

        # ── Workday searchbox / combobox ("How Did You Hear", country phone code, etc.) ──
        if field_type == "workday_searchbox":
            try:
                option_sel = (
                    "[role='option'], [role='listitem'][tabindex], "
                    "[data-automation-id='menuItem']"
                )

                # Dismiss any open dropdown via JS + keyboard Escape so the
                # <li menuItem> overlay doesn't intercept the upcoming click.
                await self.page.evaluate("""
                    () => {
                        const ev = new KeyboardEvent('keydown',
                            {key:'Escape', bubbles:true, cancelable:true});
                        const active = document.activeElement;
                        if (active) { active.dispatchEvent(ev); active.blur(); }
                        document.dispatchEvent(ev);
                    }
                """)
                await self.page.keyboard.press("Escape")
                await self.page.wait_for_timeout(200)

                # Scroll input into view so the sticky pageFooter doesn't intercept
                try:
                    el = await self.page.query_selector(locator)
                    if el:
                        await el.scroll_into_view_if_needed()
                        await self.page.wait_for_timeout(150)
                except Exception:
                    pass

                # Click the input — try normal click first, fall back to force
                try:
                    await self.page.click(locator, timeout=3_000)
                except Exception:
                    # Overlay still intercepting — force the click through
                    try:
                        await self.page.click(locator, force=True)
                    except Exception:
                        pass
                await self.page.wait_for_timeout(200)

                if value:
                    # Type to filter options, then pick best match
                    await self.page.fill(locator, value)
                    await self.page.wait_for_timeout(400)
                    try:
                        await self.page.wait_for_selector(option_sel, timeout=3_000)
                    except Exception:
                        pass
                    options = await self.page.query_selector_all(option_sel)
                    if not options:
                        # No filtered results — clear and show all
                        await self.page.fill(locator, "")
                        await self.page.wait_for_timeout(300)
                        options = await self.page.query_selector_all(option_sel)
                    best = None
                    for opt in options:
                        text = (await opt.inner_text()).strip()
                        if value.lower() in text.lower() or text.lower() in value.lower():
                            best = opt
                            break
                    if best is None and options:
                        best = options[0]
                else:
                    # No value — open dropdown and pick first option
                    try:
                        await self.page.wait_for_selector(option_sel, timeout=3_000)
                    except Exception:
                        pass
                    options = await self.page.query_selector_all(option_sel)
                    best = options[0] if options else None

                if best:
                    await best.click()
                    await self.page.wait_for_timeout(300)

                    # Two-level dropdowns (e.g. "How Did You Hear About Us"):
                    # clicking a top-level category keeps the dropdown open and
                    # shows sub-options. Detect and pick the first sub-option.
                    second_level = await self.page.query_selector_all(option_sel)
                    if not second_level:
                        # Some Workday tenants render sub-options as radio inputs
                        second_level = await self.page.query_selector_all(
                            "[data-automation-id='promptOption'] label, "
                            "[role='radio']"
                        )
                    if second_level:
                        await second_level[0].click()
                        await self.page.wait_for_timeout(150)

                    return True
                return False
            except Exception as exc:
                print(f"    [workday] searchbox fill failed: {exc}")
                return False

        # ── Native <select> ─────────────────────────────────────────────────
        if field_type == "select":
            try:
                # Try select_option first (works for native <select>)
                await self.page.select_option(locator, label=value, timeout=3_000)
                return True
            except Exception:
                pass
            try:
                # Fallback: click-and-pick (for styled Workday dropdowns)
                await self.page.click(locator)
                await self.page.wait_for_selector("[role='option']", timeout=3_000)
                options = await self.page.query_selector_all("[role='option']")
                for option in options:
                    text = (await option.inner_text()).strip()
                    if value.lower() in text.lower():
                        await option.click()
                        return True
                if options:
                    await options[0].click()
                return True
            except Exception as exc:
                print(f"    [workday] select fill failed: {exc}")
                return False

        # ── Radio group ─────────────────────────────────────────────────────
        if field_type == "radio":
            try:
                radios = await self.page.query_selector_all(locator)
                for radio in radios:
                    rid = await radio.get_attribute("id")
                    lbl_el = await self.page.query_selector(
                        f"label[for='{rid}']"
                    ) if rid else None
                    lbl_text = (await lbl_el.inner_text()).strip() if lbl_el else ""
                    val_attr = (await radio.get_attribute("value") or "").lower()
                    if (value.lower() in lbl_text.lower()
                            or lbl_text.lower() in value.lower()
                            or value.lower() == val_attr):
                        await radio.click()
                        return True
                # No label match — click first radio
                if radios:
                    await radios[0].click()
                return True
            except Exception as exc:
                print(f"    [workday] radio fill failed: {exc}")
                return False

        # ── Plain text / tel / email / number / textarea ───────────────────
        # page.fill() sets the DOM value but doesn't fire React's synthetic
        # onChange, so Workday's controlled inputs ignore it. Simulating real
        # keystrokes (click → select-all → type) triggers React correctly.
        if field_type in ("text", "tel", "email", "number", "url", "textarea"):
            try:
                await self.page.click(locator, timeout=3_000)
                await self.page.wait_for_timeout(80)
                await self.page.keyboard.press("Control+A")
                await self.page.keyboard.type(str(value), delay=10)
                # Tab away to fire blur/change events and let Workday validate
                await self.page.keyboard.press("Tab")
                return True
            except Exception as exc:
                print(f"    [workday] text fill failed ({locator}): {exc}")
                return await self.fill_field_generic(locator, value, field_type)

        return await self.fill_field_generic(locator, value, field_type)

    # ------------------------------------------------------------------ #
    # Wizard navigation                                                    #
    # ------------------------------------------------------------------ #

    async def next_section(self) -> bool:
        """
        Click Save and Continue / Next. Returns False if no next button found.

        Also detects whether Workday showed a validation error after the click
        (e.g. required fields not filled) — if so we return False so fill_form
        doesn't mistakenly think a new section loaded.
        """
        # Read the current section heading before clicking so we can compare
        current_heading = ""
        try:
            heading_el = await self.page.query_selector(
                "[data-automation-id='currentSectionTitle'], "
                "h2[data-automation-id], "
                "[role='heading'][aria-level='2']"
            )
            if heading_el:
                current_heading = (await heading_el.inner_text()).strip()
        except Exception:
            pass

        clicked = False
        for attempt in [
            lambda: self.page.locator(self.NEXT_BTN).click(timeout=5_000),
            lambda: self.page.get_by_role("button", name="Save and Continue", exact=False).click(timeout=5_000),
            lambda: self.page.get_by_role("button", name="Next", exact=False).click(timeout=3_000),
        ]:
            try:
                await attempt()
                clicked = True
                break
            except Exception:
                continue

        if not clicked:
            return None   # no button found → caller treats as truly done

        # Wait for the next section to render.
        # networkidle can stall 10s+ on Workday's long-polling XHRs, so use
        # domcontentloaded + a short fixed pause instead.
        try:
            await self.page.wait_for_load_state("domcontentloaded", timeout=8_000)
        except Exception:
            pass
        await self.page.wait_for_timeout(1_200)

        # Check for validation errors — Workday shows these in-place on the same section
        try:
            page_text = await self.page.evaluate("() => document.documentElement.innerText")
            error_phrases = [
                "this field is required",
                "required field",
                "please correct",
                "please fix",
            ]
            if any(p in (page_text or "").lower() for p in error_phrases):
                print(f"    [workday] validation error detected after next — staying on section")
                return False
        except Exception:
            pass

        # Verify the section actually changed (heading changed or URL changed)
        if current_heading:
            try:
                new_heading_el = await self.page.query_selector(
                    "[data-automation-id='currentSectionTitle'], "
                    "h2[data-automation-id], "
                    "[role='heading'][aria-level='2']"
                )
                new_heading = ""
                if new_heading_el:
                    new_heading = (await new_heading_el.inner_text()).strip()
                if new_heading and new_heading == current_heading:
                    print(f"    [workday] section heading unchanged ('{current_heading}') — advance may have failed")
                    # Still return True: button was there and clicked; Workday may just
                    # not update the heading immediately on some tenants.
            except Exception:
                pass

        return True

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
