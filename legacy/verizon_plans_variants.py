"""Run the Verizon broadband-plans automation at 3 different anti-bot
evasion levels and capture network traffic for comparison.

Usage:
    python verizon_plans_variants.py --level 1   # Worst: naked bot
    python verizon_plans_variants.py --level 2   # Medium: basic evasion
    python verizon_plans_variants.py --level 3   # Best: stealth mode
"""

from __future__ import annotations

import argparse
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime

import openpyxl
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)

from api_logger import ApiLogger

VERIZON_URL = "https://www.verizon.com/home/internet/"
ADDRESS = "140 West Street, New York, NY 10007"
LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


@dataclass
class LevelConfig:
    name: str
    headless: bool
    slow_mo: int
    viewport: dict
    user_agent: str | None
    typing_delay: int
    use_stealth: bool
    human_like_delays: bool


LEVEL_CONFIGS = {
    1: LevelConfig(
        name="level1_naked_bot",
        headless=True,
        slow_mo=0,
        viewport={"width": 800, "height": 600},
        user_agent=None,  # default Playwright UA (exposes HeadlessChrome)
        typing_delay=0,
        use_stealth=False,
        human_like_delays=False,
    ),
    2: LevelConfig(
        name="level2_basic_evasion",
        headless=False,
        slow_mo=150,
        viewport={"width": 1440, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        typing_delay=40,
        use_stealth=False,
        human_like_delays=False,
    ),
    3: LevelConfig(
        name="level3_stealth",
        headless=False,
        slow_mo=0,
        viewport=random.choice([
            {"width": 1920, "height": 1080},
            {"width": 1536, "height": 864},
            {"width": 1440, "height": 900},
        ]),
        user_agent=(
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        ),
        typing_delay=0,  # handled by human_like_type()
        use_stealth=True,
        human_like_delays=True,
    ),
}


def human_pause(min_s: float = 1.5, max_s: float = 4.0) -> None:
    time.sleep(random.uniform(min_s, max_s))


def human_like_type(page: Page, locator, text: str) -> None:
    for char in text:
        locator.type(char, delay=0)
        page.wait_for_timeout(random.randint(60, 220))


def human_like_click(page: Page, locator) -> None:
    """Move mouse to element, brief pause, then click."""
    try:
        box = locator.bounding_box(timeout=5000)
        if box:
            x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
            y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
            page.mouse.move(x, y, steps=random.randint(5, 15))
            page.wait_for_timeout(random.randint(100, 400))
            page.mouse.click(x, y)
            return
    except Exception:
        pass
    locator.click(timeout=10000)


def dismiss_cookie_banner(page: Page) -> None:
    candidates = [
        "#truste-consent-button",
        "button:has-text('Accept All')",
        "button:has-text('Accept all')",
        "button.button:has-text('Close')",
    ]
    for selector in candidates:
        try:
            for loc in page.locator(selector).all():
                if loc.is_visible():
                    loc.click(timeout=2_000)
                    page.wait_for_timeout(500)
                    return
        except Exception:
            continue


def enter_address_and_submit(page: Page, api_logger: ApiLogger, cfg: LevelConfig) -> None:
    print("Entering service address...")
    api_logger.set_phase("address_entry:typing")

    address_field = page.locator("#streetaddress, input[aria-label*='Street Address' i]").first
    address_field.wait_for(state="visible", timeout=15_000)
    address_field.click()
    address_field.fill("")

    if cfg.human_like_delays:
        human_like_type(page, address_field, ADDRESS)
        human_pause(1.0, 2.5)
    else:
        address_field.type(ADDRESS, delay=cfg.typing_delay)
        page.wait_for_timeout(1_500)

    api_logger.set_phase("address_entry:autocomplete_suggestions")
    suggestion = page.locator(
        "[role='option'], ul[role='listbox'] li, div[class*='suggest' i] li"
    ).first
    try:
        suggestion.wait_for(state="visible", timeout=5_000)
        if cfg.human_like_delays:
            human_pause(0.5, 1.5)
            human_like_click(page, suggestion)
        else:
            suggestion.click()
        print(f"  selected suggestion")
    except PlaywrightTimeoutError:
        print("  no autocomplete, pressing Enter")
        address_field.press("Enter")

    if cfg.human_like_delays:
        human_pause(0.8, 2.0)
    else:
        page.wait_for_timeout(500)

    api_logger.set_phase("address_entry:get_started_click")
    get_started = page.locator("button:has-text('Get started')").first
    get_started.wait_for(state="visible", timeout=15_000)
    if cfg.human_like_delays:
        human_like_click(page, get_started)
    else:
        get_started.click()
    print("  clicked 'Get started'")

    api_logger.set_phase("address_entry:business_residential_modal")
    residential_btn = page.locator("button:has-text('Continue as residential')").first
    try:
        residential_btn.wait_for(state="visible", timeout=6_000)
        if cfg.human_like_delays:
            human_pause(0.5, 1.5)
            human_like_click(page, residential_btn)
        else:
            residential_btn.click()
        print("  selected 'Continue as residential'")
    except PlaywrightTimeoutError:
        pass


def wait_for_offers_page(page: Page, api_logger: ApiLogger, cfg: LevelConfig) -> None:
    print("Waiting for plans to load...")
    api_logger.set_phase("offers_page:loading")
    page.wait_for_url("**/inhome/buildproducts**", timeout=30_000)
    try:
        page.locator("button.reviewDetailsbtn, button:has-text('Review details')").first.wait_for(
            state="visible", timeout=30_000
        )
    except PlaywrightTimeoutError:
        pass
    if cfg.human_like_delays:
        human_pause(2.0, 4.0)
    else:
        page.wait_for_timeout(1_500)
    dismiss_cookie_banner(page)


def click_each_plan(page: Page, api_logger: ApiLogger, cfg: LevelConfig) -> None:
    review_buttons = page.locator("button.reviewDetailsbtn, button:has-text('Review details')")
    total = review_buttons.count()
    if total == 0:
        print("  WARNING: No 'Review details' buttons found.")
        return
    print(f"Found {total} plan(s) on the offers page.")

    for index in range(total):
        print(f"\n  Opening plan {index + 1}/{total}...")
        api_logger.set_phase(f"plan_review:{index + 1}_of_{total}")
        try:
            btn = page.locator("button.reviewDetailsbtn, button:has-text('Review details')").nth(index)
            btn.scroll_into_view_if_needed(timeout=15_000)

            if cfg.human_like_delays:
                human_pause(1.0, 3.0)
                human_like_click(page, btn)
                human_pause(1.5, 3.0)
            else:
                btn.click(timeout=15_000, force=True)
                page.wait_for_timeout(1_500)

            close_details_modal(page, cfg)
            print(f"  opened and closed plan {index + 1}")
        except Exception as exc:
            print(f"  could not open plan {index + 1}: {exc}")
            close_details_modal(page, cfg)

        if cfg.human_like_delays:
            human_pause(1.0, 2.5)
        else:
            page.wait_for_timeout(1_500)


def close_details_modal(page: Page, cfg: LevelConfig) -> bool:
    close_candidates = [
        "button[aria-label$='modal Close']",
        "button[aria-label='Close']",
        "button:has-text('Close')",
    ]
    for selector in close_candidates:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=2_000):
                if cfg.human_like_delays:
                    human_like_click(page, btn)
                else:
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


def filter_excel(src_path: str, dst_path: str) -> int:
    """Remove Low/None rows, keep only High+Medium. Returns kept count."""
    wb = openpyxl.load_workbook(src_path)
    ws = wb["API Calls"]
    rows_to_delete = []
    for row_idx in range(ws.max_row, 1, -1):
        level = ws.cell(row=row_idx, column=9).value
        if level in ("None", "Low"):
            rows_to_delete.append(row_idx)
    for row_idx in rows_to_delete:
        ws.delete_rows(row_idx, 1)
    wb.save(dst_path)
    return ws.max_row - 1


def run(playwright: Playwright, level: int, proxy: str | None = None) -> None:
    cfg = LEVEL_CONFIGS[level]
    print(f"\n{'='*60}")
    print(f"  LEVEL {level}: {cfg.name}")
    print(f"  headless={cfg.headless} | stealth={cfg.use_stealth} | human_delays={cfg.human_like_delays}")
    print(f"  proxy={'yes' if proxy else 'none'}")
    print(f"{'='*60}\n")

    launch_args: dict = {"headless": cfg.headless}
    if cfg.slow_mo:
        launch_args["slow_mo"] = cfg.slow_mo
    if proxy:
        launch_args["proxy"] = {"server": proxy}

    browser: Browser = playwright.chromium.launch(**launch_args)

    context_args: dict = {"viewport": cfg.viewport}
    if cfg.user_agent:
        context_args["user_agent"] = cfg.user_agent

    if cfg.use_stealth:
        from playwright_stealth import Stealth
        stealth = Stealth()
        context: BrowserContext = browser.new_context(**context_args)
        page = context.new_page()
        stealth.apply_stealth_sync(page)
    else:
        context = browser.new_context(**context_args)
        page = context.new_page()

    api_logger = ApiLogger()
    api_logger.attach(page)

    try:
        print(f"Opening {VERIZON_URL}")
        api_logger.set_phase("landing_page:initial_load")
        page.goto(VERIZON_URL, wait_until="domcontentloaded", timeout=45_000)

        if cfg.human_like_delays:
            human_pause(2.0, 4.0)
        else:
            page.wait_for_timeout(2_000)

        api_logger.snapshot_cookies(context, "01_after_landing_page_load")
        dismiss_cookie_banner(page)

        enter_address_and_submit(page, api_logger, cfg)
        api_logger.snapshot_cookies(context, "02_after_get_started_click")

        wait_for_offers_page(page, api_logger, cfg)
        api_logger.snapshot_cookies(context, "03_after_offers_page_loaded")

        click_each_plan(page, api_logger, cfg)
        api_logger.snapshot_cookies(context, "04_after_all_plans_reviewed")
        print("\nDone. Closing browser.")
    except Exception as exc:
        print(f"\nERROR during automation: {exc}")
        api_logger.snapshot_cookies(context, "99_after_error")
    finally:
        time.sleep(1)
        os.makedirs(LOGS_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        full_path = os.path.join(LOGS_DIR, f"{cfg.name}_{ts}.xlsx")
        api_logger.save_to_excel(full_path)

        filtered_path = os.path.join(LOGS_DIR, f"{cfg.name}_filtered.xlsx")
        kept = filter_excel(full_path, filtered_path)
        print(f"Filtered to {kept} important calls -> {filtered_path}")

        context.close()
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Verizon bot-detection evasion comparison")
    parser.add_argument("--level", type=int, choices=[1, 2, 3, 4, 5], required=True,
                        help="Evasion level: 1=naked bot, 2=basic, 3=stealth, "
                             "4=patchright (real Chrome TLS), 5=nodriver (raw CDP)")
    parser.add_argument("--proxy", type=str, default=None,
                        help="Proxy URL, e.g. http://user:pass@host:port")
    args = parser.parse_args()

    if args.level == 4:
        import subprocess, sys
        cmd = [sys.executable, "verizon_patchright.py"]
        if args.proxy:
            cmd += ["--proxy", args.proxy]
        subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))
        return

    if args.level == 5:
        import subprocess, sys
        cmd = [sys.executable, "verizon_nodriver.py"]
        if args.proxy:
            cmd += ["--proxy", args.proxy]
        subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))
        return

    with sync_playwright() as p:
        run(p, args.level, proxy=args.proxy)


if __name__ == "__main__":
    main()
