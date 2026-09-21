"""Run the Frontier broadband-plans automation at 3 different anti-bot
evasion levels and capture network traffic for comparison.

Usage:
    python frontier_plans_variants.py --level 1   # Worst: naked bot
    python frontier_plans_variants.py --level 2   # Medium: basic evasion
    python frontier_plans_variants.py --level 3   # Best: stealth mode
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

FRONTIER_URL = "https://frontier.com/shop/internet"
ADDRESS = "2727 LBJ Freeway, Dallas, TX 75234"
LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "frontier")


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
        name="frontier_level1_naked_bot",
        headless=True,
        slow_mo=0,
        viewport={"width": 800, "height": 600},
        user_agent=None,
        typing_delay=0,
        use_stealth=False,
        human_like_delays=False,
    ),
    2: LevelConfig(
        name="frontier_level2_basic_evasion",
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
        name="frontier_level3_stealth",
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
        typing_delay=0,
        use_stealth=True,
        human_like_delays=True,
    ),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def human_pause(min_s: float = 1.5, max_s: float = 4.0) -> None:
    time.sleep(random.uniform(min_s, max_s))


def human_like_type(page: Page, locator, text: str) -> None:
    for char in text:
        locator.type(char, delay=0)
        page.wait_for_timeout(random.randint(60, 220))


def human_like_click(page: Page, locator) -> None:
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
        "button:has-text('Close')",
        "button:has-text('Accept All')",
        "button:has-text('Accept all')",
        "#truste-consent-button",
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


# ---------------------------------------------------------------------------
# Landing page flow  (frontier.com/shop/internet)
# ---------------------------------------------------------------------------

def enter_address_landing_page(
    page: Page, api_logger: ApiLogger, cfg: LevelConfig
) -> None:
    """Type address on the landing page and click 'Check availability'."""
    print("  Entering address on landing page...")
    api_logger.set_phase("landing:address_entry")

    address_field = page.locator(
        "input[aria-label*='Street Address' i], "
        "input[placeholder*='Enter your address' i]"
    ).first
    address_field.wait_for(state="visible", timeout=15_000)
    address_field.click()
    address_field.fill("")

    if cfg.human_like_delays:
        human_like_type(page, address_field, ADDRESS)
        human_pause(1.5, 3.0)
    else:
        address_field.type(ADDRESS, delay=cfg.typing_delay)
        page.wait_for_timeout(2_000)

    api_logger.set_phase("landing:autocomplete_select")

    suggestion = page.locator(
        "button:has-text('Dallas'), button:has-text('Johnson'), "
        "[role='option']:has-text('Dallas')"
    ).first
    try:
        suggestion.wait_for(state="visible", timeout=5_000)
        if cfg.human_like_delays:
            human_pause(0.5, 1.5)
            human_like_click(page, suggestion)
        else:
            suggestion.click()
        print("    selected autocomplete suggestion")
    except PlaywrightTimeoutError:
        print("    no autocomplete — using fill fallback")
        address_field.fill(ADDRESS)

    if cfg.human_like_delays:
        human_pause(0.5, 1.5)
    else:
        page.wait_for_timeout(500)

    api_logger.set_phase("landing:check_availability_click")
    check_btn = page.locator("button:has-text('Check availability')").first
    try:
        check_btn.wait_for(state="visible", timeout=10_000)
        if cfg.human_like_delays:
            human_like_click(page, check_btn)
        else:
            check_btn.click()
        print("    clicked 'Check availability'")
    except PlaywrightTimeoutError:
        print("    Check availability button not found, pressing Enter")
        address_field.press("Enter")


def try_enter_address_landing(
    page: Page, api_logger: ApiLogger, cfg: LevelConfig
) -> bool:
    """Try the landing page address flow; return True if it worked."""
    try:
        enter_address_landing_page(page, api_logger, cfg)
        return True
    except (PlaywrightTimeoutError, Exception) as exc:
        print(f"    landing page address failed: {exc}")
        return False


# ---------------------------------------------------------------------------
# Buy page flow  (frontier.com/buy)
# ---------------------------------------------------------------------------

def enter_address_buy_page(
    page: Page, api_logger: ApiLogger, cfg: LevelConfig
) -> None:
    """Handle the second address entry on the /buy page."""
    print("  Entering address on buy page...")
    api_logger.set_phase("buy_page:address_entry")

    address_input = page.locator(
        "[role='combobox'], "
        "input[aria-label*='address' i], "
        "input[placeholder*='Enter your address' i]"
    ).first
    try:
        address_input.wait_for(state="visible", timeout=10_000)
    except PlaywrightTimeoutError:
        print("    no address field on buy page — plans may already be shown")
        return

    address_input.click()
    address_input.fill("")

    if cfg.human_like_delays:
        human_like_type(page, address_input, ADDRESS)
        human_pause(2.0, 4.0)
    else:
        address_input.type(ADDRESS, delay=cfg.typing_delay)
        page.wait_for_timeout(3_000)

    api_logger.set_phase("buy_page:autocomplete_select")
    option = page.locator("[role='option']").first
    try:
        option.wait_for(state="visible", timeout=8_000)
        if cfg.human_like_delays:
            human_pause(0.5, 1.5)
            human_like_click(page, option)
        else:
            option.click()
        print("    selected suggestion on buy page")
    except PlaywrightTimeoutError:
        print("    no suggestions appeared on buy page")
        address_input.fill(ADDRESS)

    if cfg.human_like_delays:
        human_pause(0.5, 1.5)
    else:
        page.wait_for_timeout(500)

    api_logger.set_phase("buy_page:check_availability_click")
    check_btn = page.locator("button:has-text('Check availability')").first
    try:
        check_btn.wait_for(state="visible", timeout=10_000)
        if cfg.human_like_delays:
            human_like_click(page, check_btn)
        else:
            check_btn.click()
        print("    clicked 'Check availability' on buy page")
    except PlaywrightTimeoutError:
        print("    no Check availability button")

    api_logger.set_phase("buy_page:plans_loading")
    page.wait_for_timeout(3_000)


# ---------------------------------------------------------------------------
# Plans browsing (if plans are displayed)
# ---------------------------------------------------------------------------

def browse_plans(page: Page, api_logger: ApiLogger, cfg: LevelConfig) -> None:
    """Click on each plan card if available."""
    api_logger.set_phase("plans:browsing")

    plan_selectors = [
        "button:has-text('View plan')",
        "button:has-text('Shop now')",
        "button:has-text('Add to cart')",
        "a:has-text('Fiber 500')",
        "a:has-text('Fiber 1 Gig')",
        "a:has-text('Fiber 2 Gig')",
        "[data-testid*='plan-card'] button",
        ".plan-card button",
    ]

    for selector in plan_selectors:
        try:
            buttons = page.locator(selector)
            count = buttons.count()
            if count > 0:
                print(f"  Found {count} plan button(s) matching '{selector}'")
                for i in range(min(count, 6)):
                    api_logger.set_phase(f"plans:clicking_plan_{i+1}")
                    btn = buttons.nth(i)
                    btn.scroll_into_view_if_needed(timeout=5_000)
                    if cfg.human_like_delays:
                        human_pause(1.0, 2.5)
                        human_like_click(page, btn)
                        human_pause(1.5, 3.0)
                    else:
                        btn.click(timeout=5_000)
                        page.wait_for_timeout(1_500)

                    close_any_modal(page, cfg)
                    print(f"    clicked plan {i+1}")
                return
        except Exception:
            continue

    print("  No plan buttons found to click — page may have been blocked.")
    if cfg.human_like_delays:
        human_pause(2.0, 4.0)
    else:
        page.wait_for_timeout(3_000)

    api_logger.set_phase("plans:scrolling_page")
    for _ in range(3):
        page.keyboard.press("PageDown")
        if cfg.human_like_delays:
            human_pause(1.0, 2.0)
        else:
            page.wait_for_timeout(1_000)


def close_any_modal(page: Page, cfg: LevelConfig) -> None:
    close_candidates = [
        "button[aria-label*='Close' i]",
        "button:has-text('Close')",
        "button[aria-label$='modal Close']",
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
                return
        except Exception:
            continue
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Excel filtering
# ---------------------------------------------------------------------------

def filter_excel(src_path: str, dst_path: str) -> int:
    wb = openpyxl.load_workbook(src_path)
    ws = wb["API Calls"]
    signal_col = None
    for col_idx in range(1, ws.max_column + 1):
        if ws.cell(row=1, column=col_idx).value == "Signal Level":
            signal_col = col_idx
            break
    if signal_col is None:
        signal_col = 9

    rows_to_delete = []
    for row_idx in range(ws.max_row, 1, -1):
        level = ws.cell(row=row_idx, column=signal_col).value
        if level in ("None", "Low"):
            rows_to_delete.append(row_idx)
    for row_idx in rows_to_delete:
        ws.delete_rows(row_idx, 1)
    wb.save(dst_path)
    return ws.max_row - 1


# ---------------------------------------------------------------------------
# Main run
# ---------------------------------------------------------------------------

def run(playwright: Playwright, level: int, proxy: str | None = None) -> None:
    cfg = LEVEL_CONFIGS[level]
    print(f"\n{'='*60}")
    print(f"  FRONTIER — LEVEL {level}: {cfg.name}")
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
        # Phase 1: Landing page
        print(f"Opening {FRONTIER_URL}")
        api_logger.set_phase("landing_page:initial_load")
        page.goto(FRONTIER_URL, wait_until="domcontentloaded", timeout=45_000)

        if cfg.human_like_delays:
            human_pause(2.0, 4.0)
        else:
            page.wait_for_timeout(3_000)

        api_logger.snapshot_cookies(context, "01_after_landing_page_load")
        dismiss_cookie_banner(page)

        landing_ok = try_enter_address_landing(page, api_logger, cfg)

        if landing_ok:
            api_logger.snapshot_cookies(context, "02_after_landing_check_availability")
            api_logger.set_phase("redirect:waiting_for_buy_page")
            try:
                page.wait_for_url("**/buy**", timeout=15_000)
                print("  Redirected to buy page")
            except PlaywrightTimeoutError:
                print("  No redirect to /buy — checking current page")
        else:
            print("  Landing page blocked — navigating to /buy directly")
            api_logger.set_phase("fallback:direct_buy_page")
            page.goto("https://frontier.com/buy", wait_until="domcontentloaded", timeout=45_000)

        if cfg.human_like_delays:
            human_pause(2.0, 4.0)
        else:
            page.wait_for_timeout(3_000)

        api_logger.snapshot_cookies(context, "03_after_buy_page_load")

        # Phase 3: Enter address on buy page if needed
        current_url = page.url
        if "/buy" in current_url:
            enter_address_buy_page(page, api_logger, cfg)
            api_logger.snapshot_cookies(context, "04_after_buy_page_check")

        # Phase 4: Wait for plans to load
        api_logger.set_phase("plans_page:loading")
        if cfg.human_like_delays:
            human_pause(3.0, 6.0)
        else:
            page.wait_for_timeout(5_000)

        api_logger.snapshot_cookies(context, "05_after_plans_loaded")

        # Phase 5: Browse plans
        browse_plans(page, api_logger, cfg)
        api_logger.snapshot_cookies(context, "06_after_browsing_plans")

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
    parser = argparse.ArgumentParser(
        description="Frontier bot-detection evasion comparison"
    )
    parser.add_argument(
        "--level", type=int, choices=[1, 2, 3, 4, 5], required=True,
        help="Evasion level: 1=naked bot, 2=basic, 3=stealth, "
             "4=patchright (real Chrome TLS), 5=nodriver (raw CDP)",
    )
    parser.add_argument("--proxy", type=str, default=None,
                        help="Proxy URL, e.g. http://user:pass@host:port")
    args = parser.parse_args()

    if args.level == 4:
        import subprocess, sys
        cmd = [sys.executable, "frontier_patchright.py"]
        if args.proxy:
            cmd += ["--proxy", args.proxy]
        subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))
        return

    if args.level == 5:
        import subprocess, sys
        cmd = [sys.executable, "frontier_nodriver.py"]
        if args.proxy:
            cmd += ["--proxy", args.proxy]
        subprocess.run(cmd, cwd=os.path.dirname(os.path.abspath(__file__)))
        return

    with sync_playwright() as p:
        run(p, args.level, proxy=args.proxy)


if __name__ == "__main__":
    main()
