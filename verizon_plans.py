"""Automate Verizon's broadband plans page.

Real flow discovered by inspecting the live site (see debug_inspect.py):
    1. Open https://www.verizon.com/home/internet/
    2. Type the address into the "Enter street address" field (#streetaddress).
    3. Pick an autocomplete suggestion.
    4. Click the "Get started" button next to the address field.
    5. If Verizon flags the address as a business address, click
       "Continue as residential" on the disambiguation modal.
    6. This navigates to the offers page (verizon.com/inhome/buildproducts),
       which lists plan cards (300 Mbps, 500 Mbps, 1 Gig, 2 Gig, 5 Gig, ...),
       each with a "Review details" button that opens a details modal.
    7. For each plan: click "Review details", wait for the modal, close it.
    8. Close the browser.

The DOM on verizon.com changes frequently and uses hashed styled-components
class names for some elements. Selectors below prefer stable, semantic hooks
(ids, aria-labels, plain class names like `.reviewDetailsbtn`) and fall back
to text-based matches where possible.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime

from playwright.sync_api import (
    Browser,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from api_logger import ApiLogger


VERIZON_URL = "https://www.verizon.com/home/internet/"

# Hardcoded service address used to unlock plan availability.
ADDRESS = "140 West Street, New York, NY 10007"

LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


@dataclass
class Timing:
    """Central place to tune waits (all in milliseconds unless noted)."""

    page_load: int = 45_000
    element: int = 15_000
    offers_page_load: int = 30_000  # the offers SPA is slow to hydrate
    short_pause: float = 1.5  # seconds
    between_plans: float = 1.5  # seconds


TIMING = Timing()


def wait_for_page_settle(page: Page, timeout: int | None = None) -> None:
    """Wait for navigation to settle without hanging forever.

    Verizon's site keeps background analytics/tracking connections open, so
    Playwright's "networkidle" state rarely fires. This waits for the more
    reliable "load" event, then gives the page a short grace period for
    client-side rendering, instead of blocking on networkidle.
    """
    timeout = timeout or TIMING.page_load
    try:
        page.wait_for_load_state("load", timeout=timeout)
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(1_500)


def dismiss_cookie_banner(page: Page) -> None:
    """Close the bottom-of-page cookie/privacy banner if present."""
    candidates = [
        "#truste-consent-button",
        "button:has-text('Accept All')",
        "button:has-text('Accept all')",
        "button.button:has-text('Close')",
    ]
    for selector in candidates:
        try:
            for locator in page.locator(selector).all():
                if locator.is_visible():
                    locator.click(timeout=2_000)
                    print(f"  dismissed banner via '{selector}'")
                    page.wait_for_timeout(500)
                    return
        except Exception:
            continue


def enter_address_and_submit(page: Page, api_logger: ApiLogger) -> None:
    """Fill the address checker, pick a suggestion, and click Get started."""
    print("Entering service address...")
    api_logger.set_phase("address_entry:typing")

    address_field = page.locator("#streetaddress, input[aria-label*='Street Address' i]").first
    address_field.wait_for(state="visible", timeout=TIMING.element)

    address_field.click()
    address_field.fill("")
    address_field.type(ADDRESS, delay=40)
    page.wait_for_timeout(1_500)

    api_logger.set_phase("address_entry:autocomplete_suggestions")
    suggestion = page.locator(
        "[role='option'], ul[role='listbox'] li, div[class*='suggest' i] li"
    ).first
    try:
        suggestion.wait_for(state="visible", timeout=5_000)
        suggestion_text = suggestion.inner_text()
        suggestion.click()
        print(f"  selected suggestion: '{suggestion_text.strip()}'")
    except PlaywrightTimeoutError:
        print("  no autocomplete suggestion appeared, pressing Enter")
        address_field.press("Enter")

    page.wait_for_timeout(500)

    api_logger.set_phase("address_entry:get_started_click")
    get_started = page.locator("button:has-text('Get started')").first
    get_started.wait_for(state="visible", timeout=TIMING.element)
    get_started.click()
    print("  clicked 'Get started'")

    # Verizon sometimes shows a business-vs-residential disambiguation modal.
    api_logger.set_phase("address_entry:business_residential_modal")
    residential_btn = page.locator("button:has-text('Continue as residential')").first
    try:
        residential_btn.wait_for(state="visible", timeout=6_000)
        residential_btn.click()
        print("  selected 'Continue as residential'")
    except PlaywrightTimeoutError:
        pass  # modal did not appear for this address


def wait_for_offers_page(page: Page, api_logger: ApiLogger) -> None:
    """Wait for the plan-listing offers page to finish loading."""
    print("Waiting for plans to load...")
    api_logger.set_phase("offers_page:loading")
    page.wait_for_url("**/inhome/buildproducts**", timeout=TIMING.offers_page_load)
    try:
        page.locator("button.reviewDetailsbtn, button:has-text('Review details')").first.wait_for(
            state="visible", timeout=TIMING.offers_page_load
        )
    except PlaywrightTimeoutError:
        pass
    page.wait_for_timeout(1_500)
    dismiss_cookie_banner(page)


def close_details_modal(page: Page) -> bool:
    """Close the plan-details modal opened by 'Review details'. Returns True if closed."""
    close_candidates = [
        "button[aria-label$='modal Close']",
        "button[aria-label='Close']",
        "button:has-text('Close')",
    ]
    for selector in close_candidates:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=2_000):
                btn.click(timeout=2_000, force=True)
                page.wait_for_timeout(500)
                return True
        except Exception:
            continue

    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        return True
    except Exception:
        return False


def click_each_plan(page: Page, api_logger: ApiLogger) -> None:
    """Click 'Review details' on each plan card, then close the modal."""
    review_buttons = page.locator("button.reviewDetailsbtn, button:has-text('Review details')")
    total = review_buttons.count()
    if total == 0:
        raise RuntimeError("No 'Review details' buttons found on the offers page.")
    print(f"Found {total} plan(s) on the offers page.")

    for index in range(total):
        print(f"\nOpening plan {index + 1}/{total}...")
        api_logger.set_phase(f"plan_review:{index + 1}_of_{total}")
        try:
            # Re-query every iteration in case the DOM re-renders.
            btn = page.locator("button.reviewDetailsbtn, button:has-text('Review details')").nth(index)
            btn.scroll_into_view_if_needed(timeout=TIMING.element)
            btn.click(timeout=TIMING.element, force=True)
            page.wait_for_timeout(int(TIMING.short_pause * 1000))

            if close_details_modal(page):
                print(f"  opened plan {index + 1} details and closed it")
            else:
                print(f"  could not confirm modal close for plan {index + 1}")
        except Exception as exc:
            print(f"  could not open/close plan {index + 1}: {exc}")
            close_details_modal(page)

        page.wait_for_timeout(int(TIMING.between_plans * 1000))


def run(playwright: Playwright) -> None:
    browser: Browser = playwright.chromium.launch(headless=False, slow_mo=150)
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()

    api_logger = ApiLogger()
    api_logger.attach(page)

    try:
        print(f"Opening {VERIZON_URL}")
        api_logger.set_phase("landing_page:initial_load")
        page.goto(VERIZON_URL, wait_until="domcontentloaded", timeout=TIMING.page_load)
        page.wait_for_timeout(2_000)
        api_logger.snapshot_cookies(context, "01_after_landing_page_load")
        dismiss_cookie_banner(page)

        enter_address_and_submit(page, api_logger)
        api_logger.snapshot_cookies(context, "02_after_get_started_click")

        wait_for_offers_page(page, api_logger)
        api_logger.snapshot_cookies(context, "03_after_offers_page_loaded")

        click_each_plan(page, api_logger)
        api_logger.snapshot_cookies(context, "04_after_all_plans_reviewed")
        print("\nDone. Closing browser.")
    finally:
        time.sleep(1)
        os.makedirs(LOGS_DIR, exist_ok=True)
        excel_path = os.path.join(
            LOGS_DIR, f"api_calls_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        )
        api_logger.save_to_excel(excel_path)
        context.close()
        browser.close()


def main() -> None:
    with sync_playwright() as p:
        run(p)


if __name__ == "__main__":
    main()
