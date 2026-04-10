"""
browser/ats/linkedin.py — LinkedIn Easy Apply handler.
"""
from __future__ import annotations

import asyncio
import os
from typing import List, Optional

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

    MODAL_SELECTOR = ".jobs-easy-apply-modal, [role='dialog'].artdeco-modal"

    _NEXT_SELECTORS = [
        "button[aria-label='Continue to next step']",
        "button[aria-label*='Continue to next']",
        "button[aria-label*='next step']",
    ]
    _REVIEW_SELECTORS = [
        "button[aria-label='Review your application']",
        "button[aria-label*='Review your']",
        "button[aria-label*='Review']",
    ]
    _SUBMIT_SELECTORS = [
        "button[aria-label='Submit application']",
        "button[aria-label*='Submit application']",
        "button[aria-label*='Submit']",
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
            # Already signed in check — only .global-nav__me appears for authenticated users
            already = await self.page.query_selector(".global-nav__me")
            if already and await already.is_visible():
                print("    [linkedin] already signed in")
                return True

            print("    [linkedin] navigating to LinkedIn login page")
            await self.page.goto(self.LOGIN_URL, wait_until="domcontentloaded", timeout=30_000)
            # Wait for React to render the form
            await asyncio.sleep(2)
            print(f"    [linkedin] login page loaded — URL: {self.page.url}")

            # Fill email — page.fill() internally waits for element + actionability
            _email_filled = False
            for _sel in ("#username", "input[name='session_key']",
                         "input[autocomplete='username']", "input[type='text']"):
                try:
                    await self.page.fill(_sel, email, timeout=8_000)
                    _email_filled = True
                    print(f"    [linkedin] filled email via {_sel!r}")
                    break
                except Exception:
                    continue

            if not _email_filled:
                print(f"    [linkedin] email input not found — URL: {self.page.url}")
                return False

            # Fill password
            _pwd_sel = None
            for _sel in ("#password", "input[name='session_password']", "input[type='password']"):
                try:
                    await self.page.fill(_sel, password, timeout=5_000)
                    _pwd_sel = _sel
                    print(f"    [linkedin] filled password via {_sel!r}")
                    break
                except Exception:
                    continue

            if not _pwd_sel:
                print("    [linkedin] password input not found")
                return False

            # Submit
            _clicked = False
            for _sel in (self.LOGIN_BTN, "button:has-text('Sign in')", "button[type='submit']"):
                try:
                    el = await self.page.query_selector(_sel)
                    if el and await el.is_visible():
                        await el.click()
                        _clicked = True
                        break
                except Exception:
                    continue
            if not _clicked:
                await self.page.keyboard.press("Enter")

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
        """Extract all visible fields from the current Easy Apply modal step."""
        await asyncio.sleep(0.3)

        fields = []

        groups = await self.page.query_selector_all(
            ".jobs-easy-apply-modal .jobs-easy-apply-form-section__grouping, "
            ".jobs-easy-apply-modal .fb-form-element, "
            ".artdeco-modal .jobs-easy-apply-form-section__grouping, "
            ".artdeco-modal .fb-form-element, "
            ".jobs-easy-apply-modal [class*='form-component']"
        )

        if not groups:
            modal = await self.page.query_selector(
                ".jobs-easy-apply-modal, .artdeco-modal"
            )
            if modal:
                groups = await modal.query_selector_all(
                    "div[class*='form'], fieldset, .artdeco-text-input"
                )

        for group in groups:
            field_dict = await self._parse_group(group)
            if field_dict:
                fields.append(field_dict)

        print(f"    [linkedin] extracted {len(fields)} fields on this step")
        return fields

    async def _parse_group(self, group) -> Optional[dict]:
        """Parse a single form group into a field descriptor dict."""
        try:
            label_el = await group.query_selector("label, legend")
            if not label_el:
                return None
            raw_label = (await label_el.inner_text()).strip()
            label_text = raw_label.replace("*", "").replace("(required)", "").strip()
            if not label_text:
                return None

            select_el    = await group.query_selector("select")
            textarea_el  = await group.query_selector("textarea")
            file_el      = await group.query_selector("input[type='file']")
            checkbox_els = await group.query_selector_all("input[type='checkbox']")
            radio_els    = await group.query_selector_all("input[type='radio']")
            text_el      = await group.query_selector(
                "input[type='text'], input[type='email'], "
                "input[type='tel'], input[type='number'], "
                ".artdeco-text-input--input"
            )

            if select_el:
                return {
                    "label": label_text,
                    "field_type": "select",
                    "locator": await self._element_locator(select_el, "select"),
                    "required": True,
                    "options": await self._select_options(group),
                }

            if textarea_el:
                return {
                    "label": label_text,
                    "field_type": "textarea",
                    "locator": await self._element_locator(textarea_el, "textarea"),
                    "required": True,
                    "options": [],
                }

            if file_el:
                return {
                    "label": label_text,
                    "field_type": "file",
                    "locator": "input[type='file']",
                    "required": True,
                    "options": [],
                }

            if checkbox_els:
                options = []
                for c in checkbox_els:
                    lbl = await self._element_label(c)
                    val = await c.get_attribute("value") or ""
                    options.append(lbl or val)
                name = await checkbox_els[0].get_attribute("name") or ""
                return {
                    "label": label_text,
                    "field_type": "checkbox",
                    "locator": f"input[name='{name}']" if name else "input[type='checkbox']",
                    "required": True,
                    "options": [o for o in options if o],
                }

            if radio_els:
                options = []
                for r in radio_els:
                    lbl = await self._element_label(r)
                    val = await r.get_attribute("value") or ""
                    options.append(lbl or val)
                name = await radio_els[0].get_attribute("name") or ""
                return {
                    "label": label_text,
                    "field_type": "radio",
                    "locator": f"input[name='{name}']" if name else "input[type='radio']",
                    "required": True,
                    "options": [o for o in options if o],
                }

            if text_el:
                input_type = await text_el.get_attribute("type") or "text"
                is_typeahead = await group.query_selector(
                    "input[role='combobox'], [class*='typeahead'], "
                    "[data-test-text-selectable-option__input]"
                )
                return {
                    "label": label_text,
                    "field_type": "typeahead" if is_typeahead else input_type,
                    "locator": await self._input_locator(text_el, input_type),
                    "required": True,
                    "options": [],
                }

        except Exception as exc:
            print(f"    [linkedin] _parse_group error: {exc}")

        return None

    async def _element_locator(self, el, fallback_tag: str) -> str:
        for attr in ("id", "name"):
            val = await el.get_attribute(attr)
            if val:
                return f"#{val}" if attr == "id" else f"{fallback_tag}[name='{val}']"
        return fallback_tag

    async def _input_locator(self, text_el, input_type: str) -> str:
        for attr in (
            "id",
            "data-test-single-typeahead-entity-form-component-id",
            "data-test-text-entity-list-form-item",
            "name",
        ):
            val = await text_el.get_attribute(attr)
            if val:
                return f"#{val}" if attr == "id" else f"[{attr}='{val}']"
        return f"input[type='{input_type}']"

    async def _select_options(self, container) -> List[str]:
        try:
            options = await container.query_selector_all("option")
            result = []
            for o in options:
                val = (await o.get_attribute("value") or "").strip()
                text = (await o.inner_text()).strip()
                if val and text and text.lower() not in (
                    "select an option", "please select", "-select-", ""
                ):
                    result.append(text)
            return result
        except Exception:
            return []

    async def _element_label(self, input_el) -> str:
        try:
            el_id = await input_el.get_attribute("id")
            if el_id:
                label = await self.page.query_selector(f"label[for='{el_id}']")
                if label:
                    return (await label.inner_text()).strip()
        except Exception:
            pass
        return ""

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
        """Advance to the next modal step. Returns False on final step."""
        try:
            # Check for Submit button (final step)
            for sel in self._SUBMIT_SELECTORS:
                btn = await self.page.query_selector(sel)
                if btn and await btn.is_visible():
                    return False

            # Try Review, then Next/Continue
            for selectors in (self._REVIEW_SELECTORS, self._NEXT_SELECTORS):
                for sel in selectors:
                    btn = await self.page.query_selector(sel)
                    if btn and await btn.is_visible():
                        await btn.click()
                        await asyncio.sleep(0.5)
                        return True

            # Footer primary button fallback
            footer_btn = await self.page.query_selector(self._FOOTER_PRIMARY)
            if footer_btn and await footer_btn.is_visible():
                label = (
                    (await footer_btn.get_attribute("aria-label") or "") +
                    (await footer_btn.inner_text())
                ).lower()
                if "submit" in label:
                    return False
                await footer_btn.click()
                await asyncio.sleep(0.5)
                return True

            return False
        except Exception as exc:
            print(f"    [linkedin] next_section error: {exc}")
            return False

    # ------------------------------------------------------------------ #
    # Submit                                                               #
    # ------------------------------------------------------------------ #

    async def submit_application(self) -> bool:
        """Click the Submit button and verify the application was sent."""
        try:
            btn = None
            for sel in self._SUBMIT_SELECTORS:
                candidate = await self.page.query_selector(sel)
                if candidate and await candidate.is_visible():
                    btn = candidate
                    break

            if not btn:
                footer = await self.page.query_selector(self._FOOTER_PRIMARY)
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
