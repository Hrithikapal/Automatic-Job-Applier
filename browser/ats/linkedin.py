"""
browser/ats/linkedin.py — LinkedIn Easy Apply handler.
"""
from __future__ import annotations

import asyncio
import os
from typing import List

from browser.ats.base import BaseATSHandler
from browser.session import BrowserSession


class LinkedInHandler(BaseATSHandler):

    LOGIN_URL = "https://www.linkedin.com/login"
    EMAIL_INPUT = "#username"
    PASSWORD_INPUT = "#password"
    LOGIN_BTN = "button[data-litms-control-urn='login-submit'], button[type='submit']"

    _EASY_APPLY_SELECTORS = [
        "a[aria-label*='Easy Apply']",
        "button[aria-label*='Easy Apply']",
        "a[aria-label*='Apply']:not([aria-label*='company site'])",
        "button[aria-label*='Apply']:not([aria-label*='company site'])",
        "a.jobs-apply-button",
        "button.jobs-apply-button",
        ".jobs-s-apply a",
        ".jobs-s-apply button",
        ".jobs-apply-button--top-card a",
        ".jobs-apply-button--top-card button",
        "[data-control-name='jobdetails_topcard_inapply']",
        "a:has-text('Easy Apply')",
        "button:has-text('Easy Apply')",
        "a:has-text('Apply')",
        "button:has-text('Apply')",
    ]

    MODAL_SELECTOR = ".jobs-easy-apply-modal, [role='dialog']"

    _NEXT_SELECTORS = [
        "button[aria-label='Continue to next step']",
        "button[aria-label*='Continue to next']",
        "button[aria-label*='next step']",
        "button:has-text('Next')",
        "button:has-text('Continue')",
    ]
    _REVIEW_SELECTORS = [
        "button[aria-label='Review your application']",
        "button[aria-label*='Review your']",
        "button[aria-label*='Review']",
        "button:has-text('Review')",
    ]
    _SUBMIT_SELECTORS = [
        "button[aria-label='Submit application']",
        "button[aria-label*='Submit application']",
        "button:has-text('Submit application')",
        "button:has-text('Submit')",
    ]

    _FOOTER_PRIMARY = (
        ".jobs-easy-apply-modal footer button.artdeco-button--primary, "
        ".artdeco-modal__actionbar button.artdeco-button--primary"
    )

    def __init__(self, session: BrowserSession):
        super().__init__(session)

    # ------------------------------------------------------------------ #
    # Detection                                                            #
    # ------------------------------------------------------------------ #

    async def detect(self) -> bool:
        try:
            el = await self.page.query_selector(
                "[data-job-id], .jobs-apply-button, .jobs-s-apply"
            )
            return el is not None
        except Exception:
            return False

    # ------------------------------------------------------------------ #
    # Authentication                                                       #
    # ------------------------------------------------------------------ #

    async def sign_in(self, email: str, password: str) -> bool:
        """Sign in via linkedin.com/login before navigating to the job page."""
        try:
            already = await self.page.query_selector(".global-nav__me")
            if already and await already.is_visible():
                print("    [linkedin] already signed in")
                return True

            print("    [linkedin] signing in")
            await self.page.goto(self.LOGIN_URL, wait_until="load", timeout=30_000)

            # Fill email — page.fill waits for element to appear + be editable
            try:
                await self.page.fill("#username", email, timeout=10_000)
            except Exception:
                # Fallback: semantic label (works even if LinkedIn changes IDs)
                await self.page.get_by_label("Email or phone", exact=False).first.fill(
                    email, timeout=5_000)
            print("    [linkedin] filled email")

            # Fill password
            try:
                await self.page.fill("#password", password, timeout=5_000)
            except Exception:
                await self.page.get_by_label("Password", exact=False).first.fill(
                    password, timeout=5_000)
            print("    [linkedin] filled password")

            # Click Sign in
            await self.page.click("button[type='submit']", timeout=5_000)
            await self.page.wait_for_load_state("load", timeout=20_000)

            if "checkpoint" in self.page.url or "challenge" in self.page.url:
                print("    [linkedin] 2FA / CAPTCHA required — manual intervention needed")
                return False

            print("    [linkedin] signed in successfully")
            return True

        except Exception as exc:
            print(f"    [linkedin] sign_in failed: {exc}")
            return False

    # ------------------------------------------------------------------ #
    # Navigation                                                           #
    # ------------------------------------------------------------------ #

    async def navigate_to_apply(self, job_url: str) -> bool:
        """Navigate to job URL and open the Easy Apply modal."""
        try:
            await self.page.goto(job_url, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(2)

            # Close any auth popup (instant query — no per-selector waiting)
            await self._close_authwall_popup()

            # Find and click Apply (retry once after extra wait if not found)
            apply_btn = await self._find_apply_button()
            if not apply_btn:
                print("    [linkedin] Apply button not found on first try — waiting for React")
                await asyncio.sleep(3)
                apply_btn = await self._find_apply_button()
            if not apply_btn:
                print("    [linkedin] Apply button not found")
                return False

            print("    [linkedin] clicking Apply button")
            await apply_btn.click()
            await asyncio.sleep(1)

            # Check if a sign-in modal appeared instead of Easy Apply modal
            signin_input = await self.page.query_selector(
                "input[name='session_key'], #username, input[type='email']"
            )
            if signin_input and await signin_input.is_visible():
                print("    [linkedin] sign-in modal appeared after Apply click — signing in")
                email = os.getenv("LINKEDIN_EMAIL", "")
                password = os.getenv("LINKEDIN_PASSWORD", "")
                await self.page.fill("input[name='session_key'], #username", email)
                await self.page.fill("input[type='password']", password)
                for _s in ("button:has-text('Sign in')", "button[type='submit']"):
                    _b = await self.page.query_selector(_s)
                    if _b and await _b.is_visible():
                        await _b.click()
                        break
                await self.page.wait_for_load_state("load", timeout=15_000)
                await asyncio.sleep(0.5)
                # Re-navigate and click Apply again
                await self.page.goto(job_url, wait_until="load", timeout=30_000)
                await asyncio.sleep(1)
                apply_btn = await self._find_apply_button()
                if not apply_btn:
                    print("    [linkedin] Apply button not found after sign-in")
                    return False
                await apply_btn.click()
                await asyncio.sleep(1)

            # Confirm modal opened
            try:
                await self.page.wait_for_selector(self.MODAL_SELECTOR, timeout=6_000)
                print("    [linkedin] Easy Apply modal opened")
                return True
            except Exception:
                print("    [linkedin] Easy Apply modal did not open")
                return False

        except Exception as exc:
            print(f"    [linkedin] navigate_to_apply failed: {exc}")
            return False

    async def _close_authwall_popup(self) -> bool:
        """Instantly dismiss auth-wall popup using query_selector (no timeout wait)."""
        _CLOSE_SELECTORS = [
            "button[aria-label='Dismiss']",
            "button[aria-label='Close']",
            ".artdeco-modal__dismiss",
            ".modal__dismiss",
            "[data-test-modal-close-btn]",
            ".modal__header button",
        ]
        for sel in _CLOSE_SELECTORS:
            try:
                el = await self.page.query_selector(sel)
                if el and await el.is_visible():
                    await el.click()
                    print(f"    [linkedin] closed auth wall popup via {sel!r}")
                    return True
            except Exception:
                continue
        return False

    async def _find_visible_button(self, selectors: list) -> object:
        """Try CSS selectors using instant query_selector (combined wait already ran)."""
        for selector in selectors:
            try:
                el = await self.page.query_selector(selector)
                if el and await el.is_visible():
                    text = (await el.inner_text()).strip().lower()
                    if "company site" in text:
                        continue
                    print(f"    [linkedin] found button via {selector!r}: {text!r}")
                    return el
            except Exception:
                continue
        return None

    async def _find_apply_button(self) -> object:
        """
        Find Apply/Easy Apply button.
        Waits up to 15s for the button to appear (React may render it late),
        then falls back to a full button scan.
        """
        # Wait for any apply button/link to appear in the DOM first
        _combined = (
            "a[aria-label*='Easy Apply'], "
            "button[aria-label*='Easy Apply'], "
            "a[aria-label*='Apply'], "
            "button[aria-label*='Apply'], "
            "a.jobs-apply-button, "
            "button.jobs-apply-button, "
            ".jobs-s-apply a, "
            ".jobs-s-apply button, "
            ".jobs-apply-button--top-card a"
        )
        try:
            await self.page.wait_for_selector(_combined, timeout=15_000)
            print("    [linkedin] Apply button detected in DOM")
        except Exception:
            print("    [linkedin] combined selector timed out after 15s")

        btn = await self._find_visible_button(self._EASY_APPLY_SELECTORS)
        if btn:
            return btn

        # Fallback: scan all buttons and anchors by text
        print("    [linkedin] CSS selectors failed — scanning all buttons")
        try:
            all_buttons = await self.page.query_selector_all("button, a[aria-label*='Apply'], a[href*='/apply/']")
            print(f"    [linkedin] found {len(all_buttons)} clickable elements to scan")
            for b in all_buttons:
                try:
                    if not await b.is_visible():
                        continue
                    text = (await b.inner_text()).strip()
                    if not text:
                        text = (await b.get_attribute("aria-label") or "").strip()
                    text_lower = text.lower()
                    # Prefer 'Easy Apply', accept plain 'Apply' but reject 'company site'
                    if "apply" in text_lower and "company site" not in text_lower:
                        print(f"    [linkedin] found Apply button via scan: {text!r}")
                        return b
                except Exception:
                    continue
        except Exception as exc:
            print(f"    [linkedin] button scan failed: {exc}")
        return None

    # ------------------------------------------------------------------ #
    # Form extraction                                                      #
    # ------------------------------------------------------------------ #

    async def extract_form_fields(self) -> List[dict]:
        """
        Extract all visible fields from the current Easy Apply modal step.
        Uses semantic HTML selectors (not LinkedIn class names) to survive
        SDUI markup changes.  Each field includes ``current_value`` so the
        caller can skip pre-filled fields.
        """
        await asyncio.sleep(0.5)

        fields: List[dict] = []

        # Find the modal
        modal = await self.page.query_selector(
            "[role='dialog'], .jobs-easy-apply-modal, .artdeco-modal"
        )
        if not modal:
            print("    [linkedin] no modal found for field extraction")
            return fields

        # --- Select dropdowns ---
        _PLACEHOLDER_VALUES = {
            "select an option", "please select", "-select-", "select", "",
        }
        for select in await modal.query_selector_all("select"):
            try:
                if not await select.is_visible():
                    continue
                label = await self._label_for(select)
                if not label:
                    continue
                options = await self._options_from_select(select)
                current = await select.evaluate(
                    "el => (el.options[el.selectedIndex] || {}).text || ''"
                )
                # Treat placeholder text as empty (not pre-filled)
                if current.strip().lower() in _PLACEHOLDER_VALUES:
                    current = ""
                locator = await self._locator_for(select, "select")
                fields.append({
                    "label": label, "field_type": "select",
                    "locator": locator, "required": True,
                    "options": options, "current_value": current.strip(),
                })
            except Exception:
                continue

        # --- Text / tel / email / number inputs ---
        for inp in await modal.query_selector_all(
            "input:not([type='hidden']):not([type='file'])"
            ":not([type='radio']):not([type='checkbox'])"
        ):
            try:
                if not await inp.is_visible():
                    continue
                label = await self._label_for(inp)
                if not label:
                    continue
                input_type = await inp.get_attribute("type") or "text"
                current = await inp.input_value()
                role = await inp.get_attribute("role") or ""
                ftype = "typeahead" if role == "combobox" else input_type
                locator = await self._locator_for(inp, f"input[type='{input_type}']")
                fields.append({
                    "label": label, "field_type": ftype,
                    "locator": locator, "required": True,
                    "options": [], "current_value": current.strip(),
                })
            except Exception:
                continue

        # --- Textareas ---
        for ta in await modal.query_selector_all("textarea"):
            try:
                if not await ta.is_visible():
                    continue
                label = await self._label_for(ta)
                if not label:
                    continue
                current = await ta.input_value()
                locator = await self._locator_for(ta, "textarea")
                fields.append({
                    "label": label, "field_type": "textarea",
                    "locator": locator, "required": True,
                    "options": [], "current_value": current.strip(),
                })
            except Exception:
                continue

        # --- Radio groups (e.g. resume selection) ---
        # If at least one radio is checked, the section is pre-filled → skip.
        radios = await modal.query_selector_all("input[type='radio']")
        any_checked = False
        for r in radios:
            try:
                if await r.is_checked():
                    any_checked = True
                    break
            except Exception:
                pass
        if radios and not any_checked:
            label = "Resume"
            for r in radios:
                lbl = await self._label_for(r)
                if lbl:
                    label = lbl
                    break
            name = await radios[0].get_attribute("name") or ""
            fields.append({
                "label": label, "field_type": "radio",
                "locator": f"input[name='{name}']" if name else "input[type='radio']",
                "required": True, "options": [], "current_value": "",
            })

        # --- File inputs ---
        for fi in await modal.query_selector_all("input[type='file']"):
            try:
                label = await self._label_for(fi) or "Resume"
                locator = await self._locator_for(fi, "input[type='file']")
                fields.append({
                    "label": label, "field_type": "file",
                    "locator": locator, "required": True,
                    "options": [], "current_value": "",
                })
            except Exception:
                continue

        print(f"    [linkedin] extracted {len(fields)} fields on this step")
        for f in fields:
            tag = " (pre-filled)" if f.get("current_value") else ""
            print(f"      - {f['label']} [{f['field_type']}]{tag}")
        return fields

    # ------------------------------------------------------------------ #
    # Form-extraction helpers                                              #
    # ------------------------------------------------------------------ #

    async def _label_for(self, element) -> str:
        """Find the visible label text for a form element."""
        try:
            # 1. label[for=id]
            el_id = await element.get_attribute("id")
            if el_id:
                lbl = await self.page.query_selector(f"label[for='{el_id}']")
                if lbl:
                    return self._clean_label(await lbl.inner_text())

            # 2. aria-label / aria-labelledby
            aria = await element.get_attribute("aria-label")
            if aria:
                return self._clean_label(aria)
            aria_by = await element.get_attribute("aria-labelledby")
            if aria_by:
                lbl = await self.page.query_selector(f"#{aria_by}")
                if lbl:
                    return self._clean_label(await lbl.inner_text())

            # 3. Walk up DOM looking for label / legend / visible text
            text = await element.evaluate("""el => {
                // ancestor label
                const lab = el.closest('label');
                if (lab) return lab.textContent;
                // sibling / parent text node
                let node = el.parentElement;
                for (let i = 0; i < 4 && node; i++) {
                    const lbl = node.querySelector('label, legend');
                    if (lbl) return lbl.textContent;
                    // first non-empty text child that isn't the element itself
                    for (const c of node.children) {
                        if (c !== el && c.offsetHeight > 0) {
                            const t = c.textContent.trim();
                            if (t && t.length < 120) return t;
                        }
                    }
                    node = node.parentElement;
                }
                return '';
            }""")
            if text:
                return self._clean_label(text)
        except Exception:
            pass
        return ""

    @staticmethod
    def _clean_label(raw: str) -> str:
        return raw.replace("*", "").replace("(required)", "").strip()

    async def _locator_for(self, el, fallback: str) -> str:
        """Build a Playwright selector for a form element."""
        for attr in ("id", "name"):
            val = await el.get_attribute(attr)
            if val:
                return f"#{val}" if attr == "id" else f"{fallback}[name='{val}']"
        return fallback

    async def _options_from_select(self, select_el) -> List[str]:
        """Extract option texts from a <select> element."""
        result = []
        try:
            for o in await select_el.query_selector_all("option"):
                text = (await o.inner_text()).strip()
                val = (await o.get_attribute("value") or "").strip()
                if text and val and text.lower() not in (
                    "select an option", "please select", "-select-", ""
                ):
                    result.append(text)
        except Exception:
            pass
        return result

    # ------------------------------------------------------------------ #
    # Fill                                                                 #
    # ------------------------------------------------------------------ #

    async def fill_field(self, locator: str, value: str, field_type: str) -> bool:
        """Fill a single field."""
        if field_type == "typeahead":
            return await self._fill_typeahead(locator, value)
        if field_type in ("text", "email", "tel", "number"):
            try:
                await self.page.triple_click(locator)
            except Exception:
                pass
        return await self.fill_field_generic(locator, value, field_type)

    async def _fill_typeahead(self, locator: str, value: str) -> bool:
        try:
            await self.page.triple_click(locator)
            await self.page.type(locator, value, delay=20)
            await asyncio.sleep(0.5)

            suggestion_selectors = [
                ".basic-typeahead__selectable",
                "[class*='typeahead__selectable']",
                "li[data-test-text-selectable-option]",
                "[role='option']",
                "[role='listbox'] li",
            ]
            for sel in suggestion_selectors:
                suggestion = await self.page.query_selector(sel)
                if suggestion and await suggestion.is_visible():
                    await suggestion.click()
                    return True

            await self.page.press(locator, "Tab")
            return True
        except Exception as exc:
            print(f"    [linkedin] typeahead fill failed for {locator!r}: {exc}")
            try:
                await self.page.fill(locator, value)
                return True
            except Exception:
                return False

    # ------------------------------------------------------------------ #
    # Section navigation                                                   #
    # ------------------------------------------------------------------ #

    async def next_section(self) -> bool:
        """
        Advance to the next modal step.
        Returns:
          True  — clicked Next/Review, advanced to a new section
          None  — Submit button found (final page) or no button → form complete
          False — clicked but validation error kept us on the same page
        """
        try:
            modal = await self.page.query_selector("[role='dialog']")
            target = modal or self.page

            # Check for Submit button → final step, don't click
            for sel in self._SUBMIT_SELECTORS:
                btn = await target.query_selector(sel)
                if btn and await btn.is_visible():
                    print("    [linkedin] Submit button visible — final step")
                    return None

            # Try Review, then Next/Continue
            for selectors in (self._REVIEW_SELECTORS, self._NEXT_SELECTORS):
                for sel in selectors:
                    btn = await target.query_selector(sel)
                    if btn and await btn.is_visible():
                        text = (await btn.inner_text()).strip()
                        print(f"    [linkedin] clicking '{text}' button")
                        await btn.click()
                        await asyncio.sleep(1)
                        return True

            # Footer primary button fallback
            footer_btn = await target.query_selector(self._FOOTER_PRIMARY)
            if footer_btn and await footer_btn.is_visible():
                label = (
                    (await footer_btn.get_attribute("aria-label") or "") +
                    (await footer_btn.inner_text())
                ).lower()
                if "submit" in label:
                    return None
                await footer_btn.click()
                await asyncio.sleep(0.5)
                return True

            return None
        except Exception as exc:
            print(f"    [linkedin] next_section error: {exc}")
            return None

    # ------------------------------------------------------------------ #
    # Submit                                                               #
    # ------------------------------------------------------------------ #

    async def submit_application(self) -> bool:
        """Click the Submit button and verify the application was sent."""
        try:
            modal = await self.page.query_selector("[role='dialog']")
            target = modal or self.page

            btn = None
            for sel in self._SUBMIT_SELECTORS:
                candidate = await target.query_selector(sel)
                if candidate and await candidate.is_visible():
                    btn = candidate
                    break

            if not btn:
                footer = await target.query_selector(self._FOOTER_PRIMARY)
                if footer and await footer.is_visible():
                    label = (
                        (await footer.get_attribute("aria-label") or "") +
                        (await footer.inner_text())
                    ).lower()
                    if "submit" in label:
                        btn = footer

            if not btn:
                print("    [linkedin] submit button not found")
                return False

            print("    [linkedin] clicking Submit application")
            await btn.click()
            await asyncio.sleep(1)

            confirm_selectors = [
                ".artdeco-inline-feedback--success",
                "[class*='success-banner']",
                ".jobs-easy-apply-modal h3",
                "[aria-live='polite'] h3",
                ".artdeco-modal h3",
                ".artdeco-modal p",
            ]
            for sel in confirm_selectors:
                el = await self.page.query_selector(sel)
                if el:
                    text = (await el.inner_text()).strip().lower()
                    if any(kw in text for kw in ("sent", "submitted", "applied", "success")):
                        print(f"    [linkedin] application submitted — '{text}'")
                        await self._dismiss_confirmation_modal()
                        return True

            print("    [linkedin] submitted (confirmation text not detected)")
            await self._dismiss_confirmation_modal()
            return True

        except Exception as exc:
            print(f"    [linkedin] submit_application failed: {exc}")
            return False

    async def _dismiss_confirmation_modal(self) -> None:
        try:
            for sel in (
                "button[aria-label='Dismiss']",
                "button[aria-label='Close']",
                ".artdeco-modal__dismiss",
            ):
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    break
        except Exception:
            pass
