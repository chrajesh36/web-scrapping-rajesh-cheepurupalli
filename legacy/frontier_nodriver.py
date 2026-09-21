"""Level 5: Frontier broadband-plans automation using nodriver.

Raw CDP connection to Chrome — zero automation fingerprint.
Combined with Bezier mouse, log-normal typing, and warm-up browsing.

Usage:
    python frontier_nodriver.py [--proxy URL]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import time
from datetime import datetime
from urllib.parse import urlparse

import nodriver as uc
import nodriver.cdp.network as net
import nodriver.cdp.storage as storage_cdp
import openpyxl

from api_logger import (
    ApiCallRecord,
    ApiLogger,
    CookieSnapshotRow,
    VENDOR_SIGNATURES,
    KNOWN_BOT_COOKIE_HINTS,
    _clean,
    _pretty,
    _matches_any,
)
from behavior import (
    async_bezier_click,
    async_lognormal_type,
    async_natural_scroll,
    async_warmup_browse,
    reading_pause,
)

FRONTIER_URL = "https://frontier.com/shop/internet"
ADDRESS = "2727 LBJ Freeway, Dallas, TX 75234"
LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "frontier")
LEVEL_NAME = "frontier_level5_nodriver"


class CdpNetworkLogger:
    """Captures network traffic via CDP events into an ApiLogger."""

    def __init__(self, api_logger: ApiLogger):
        self.api_logger = api_logger
        self._pending: dict[str, dict] = {}

    async def enable(self, tab) -> None:
        tab.add_handler(net.RequestWillBeSent, self._on_request)
        tab.add_handler(net.ResponseReceived, self._on_response)
        await tab.send(net.enable())

    def _on_request(self, event: net.RequestWillBeSent) -> None:
        req = event.request
        resource_type = (event.type_.value if event.type_ else "other").lower()
        if resource_type not in self.api_logger.resource_types:
            return
        headers_dict = dict(req.headers) if req.headers else {}
        cookies = headers_dict.get("cookie", headers_dict.get("Cookie", ""))
        payload = ""
        if req.has_post_data and req.post_data:
            payload = _clean(_pretty(req.post_data))
        elif req.has_post_data:
            payload = "<binary/non-text payload>"

        self._pending[str(event.request_id)] = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "phase": self.api_logger.current_phase,
            "method": req.method,
            "resource_type": resource_type,
            "url": req.url,
            "host": urlparse(req.url).netloc,
            "request_headers": _clean(json.dumps(headers_dict, indent=2)),
            "request_cookies": _clean(cookies),
            "request_payload": payload,
            "start_time": time.time(),
        }

    def _on_response(self, event: net.ResponseReceived) -> None:
        req_id = str(event.request_id)
        pending = self._pending.pop(req_id, None)
        if pending is None:
            return
        resp = event.response
        duration_ms = f"{(time.time() - pending['start_time']) * 1000:.0f}"
        resp_headers_dict = dict(resp.headers) if resp.headers else {}
        set_cookie = resp_headers_dict.get("set-cookie", "")

        self.api_logger._counter += 1
        self.api_logger.records.append(
            ApiCallRecord(
                index=self.api_logger._counter,
                timestamp=pending["timestamp"],
                phase=pending["phase"],
                method=pending["method"],
                resource_type=pending["resource_type"],
                host=pending["host"],
                url=_clean(pending["url"]),
                request_headers=pending["request_headers"],
                request_cookies=pending["request_cookies"],
                request_payload=pending["request_payload"],
                status=resp.status,
                status_text=_clean(resp.status_text or ""),
                response_headers=_clean(json.dumps(resp_headers_dict, indent=2)),
                response_set_cookie=_clean(set_cookie),
                response_body="<CDP: body not captured inline>",
                duration_ms=duration_ms,
            )
        )


async def snapshot_cookies_cdp(tab, api_logger: ApiLogger, label: str) -> None:
    try:
        cookies = await tab.send(storage_cdp.get_cookies())
        for c in cookies:
            name = c.name or ""
            name_lower = name.lower()
            vendor_guess = ""
            for vendor, sigs in VENDOR_SIGNATURES.items():
                if _matches_any(name_lower, [s.lower() for s in sigs]):
                    vendor_guess = vendor
                    break
            if not vendor_guess and _matches_any(name_lower, KNOWN_BOT_COOKIE_HINTS):
                vendor_guess = "Unclassified bot/fraud-signal cookie"
            api_logger.cookie_snapshots.append(
                CookieSnapshotRow(
                    label=label,
                    name=name,
                    value=_clean(str(c.value or "")),
                    domain=c.domain or "",
                    path=c.path or "",
                    http_only=c.http_only if hasattr(c, "http_only") else False,
                    secure=c.secure if hasattr(c, "secure") else False,
                    same_site=str(c.same_site) if hasattr(c, "same_site") else "",
                    vendor_guess=vendor_guess,
                )
            )
    except Exception as exc:
        print(f"  Cookie snapshot '{label}' failed: {exc}")


async def dismiss_cookie_banner(tab) -> None:
    for text in ["Close", "Accept All", "Accept all"]:
        try:
            btn = await tab.find(text, timeout=2)
            if btn:
                await btn.click()
                await asyncio.sleep(0.5)
                return
        except Exception:
            continue


async def enter_address_landing(tab, api_logger: ApiLogger) -> bool:
    """Try address entry on landing page; return True on success."""
    print("  Entering address on landing page...")
    api_logger.set_phase("landing:address_entry")
    try:
        address_field = await tab.query_selector(
            "input[aria-label*='Street Address'], input[placeholder*='Enter your address']"
        )
        if not address_field:
            address_field = await tab.find("Enter your address", timeout=10)
        if not address_field:
            print("    no address field found on landing")
            return False

        await address_field.click()
        await address_field.clear_input()
        await async_lognormal_type(tab, address_field, ADDRESS)
        await asyncio.sleep(random.uniform(1.5, 3.0))

        api_logger.set_phase("landing:autocomplete_select")
        try:
            suggestion = await tab.find("Dallas", timeout=5)
            if suggestion:
                await asyncio.sleep(random.uniform(0.5, 1.5))
                await suggestion.click()
                print("    selected autocomplete suggestion")
        except Exception:
            print("    no autocomplete")

        await asyncio.sleep(random.uniform(0.5, 1.5))
        api_logger.set_phase("landing:check_availability_click")
        try:
            check_btn = await tab.find("Check availability", timeout=8)
            if check_btn:
                await check_btn.click()
                print("    clicked 'Check availability'")
        except Exception:
            pass

        return True
    except Exception as exc:
        print(f"    landing page address failed: {exc}")
        return False


async def enter_address_buy_page(tab, api_logger: ApiLogger) -> None:
    print("  Entering address on buy page...")
    api_logger.set_phase("buy_page:address_entry")
    try:
        address_input = await tab.query_selector(
            "[role='combobox'], input[aria-label*='address'], "
            "input[placeholder*='Enter your address']"
        )
        if not address_input:
            address_input = await tab.find("Enter your address", timeout=8)
        if not address_input:
            print("    no address field on buy page")
            return

        await address_input.click()
        await address_input.clear_input()
        await async_lognormal_type(tab, address_input, ADDRESS)
        await asyncio.sleep(random.uniform(2.0, 4.0))

        api_logger.set_phase("buy_page:autocomplete_select")
        try:
            option = await tab.query_selector("[role='option']")
            if option:
                await asyncio.sleep(random.uniform(0.5, 1.5))
                await option.click()
                print("    selected suggestion on buy page")
        except Exception:
            pass

        await asyncio.sleep(random.uniform(0.5, 1.5))
        api_logger.set_phase("buy_page:check_availability_click")
        try:
            check_btn = await tab.find("Check availability", timeout=8)
            if check_btn:
                await check_btn.click()
                print("    clicked 'Check availability' on buy page")
        except Exception:
            pass

        api_logger.set_phase("buy_page:plans_loading")
        await asyncio.sleep(3)
    except Exception as exc:
        print(f"    buy page address entry failed: {exc}")


async def browse_plans(tab, api_logger: ApiLogger) -> None:
    api_logger.set_phase("plans:browsing")
    for text in ["View plan", "Shop now", "Add to cart",
                 "Fiber 500", "Fiber 1 Gig", "Fiber 2 Gig"]:
        try:
            buttons = await tab.find_all(text)
            if buttons:
                print(f"  Found {len(buttons)} button(s) with text '{text}'")
                for i, btn in enumerate(buttons[:6]):
                    api_logger.set_phase(f"plans:clicking_plan_{i+1}")
                    await btn.scroll_into_view()
                    await asyncio.sleep(random.uniform(1.0, 2.5))
                    await btn.click()
                    await asyncio.sleep(random.uniform(1.5, 3.0))
                    await close_any_modal(tab)
                    print(f"    clicked plan {i+1}")
                return
        except Exception:
            continue

    print("  No plan buttons found — page may have been blocked.")
    api_logger.set_phase("plans:scrolling_page")
    for _ in range(3):
        await tab.scroll_down(300)
        await asyncio.sleep(random.uniform(1.0, 2.0))


async def close_any_modal(tab) -> None:
    try:
        btn = await tab.find("Close", timeout=2)
        if btn:
            await btn.click()
            await asyncio.sleep(0.5)
            return
    except Exception:
        pass
    try:
        await tab.send(uc.cdp.input_.dispatch_key_event(
            type_="keyDown", key="Escape", code="Escape",
            windows_virtual_key_code=27, native_virtual_key_code=27,
        ))
        await asyncio.sleep(0.5)
    except Exception:
        pass


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


async def run(proxy: str | None = None) -> None:
    print(f"\n{'='*60}")
    print(f"  FRONTIER — LEVEL 5: nodriver (raw CDP, zero artifacts)")
    print(f"  headless=False | bezier_mouse=True | lognormal_typing=True")
    print(f"  warmup_browse=15s | proxy={'yes' if proxy else 'none'}")
    print(f"{'='*60}\n")

    browser_args = []
    if proxy:
        browser_args.append(f"--proxy-server={proxy}")

    browser = await uc.start(
        headless=False,
        browser_args=browser_args or None,
    )

    tab = await browser.get(FRONTIER_URL)

    api_logger = ApiLogger()
    cdp_logger = CdpNetworkLogger(api_logger)
    await cdp_logger.enable(tab)

    try:
        print(f"Opened {FRONTIER_URL}")
        api_logger.set_phase("landing_page:initial_load")
        await asyncio.sleep(random.uniform(3.0, 5.0))

        await snapshot_cookies_cdp(tab, api_logger, "01_after_landing_page_load")
        await dismiss_cookie_banner(tab)

        print("Warm-up browsing for ~15 seconds...")
        api_logger.set_phase("warmup:browsing")
        await async_warmup_browse(tab, duration_s=15.0)
        await snapshot_cookies_cdp(tab, api_logger, "02_after_warmup_browse")

        landing_ok = await enter_address_landing(tab, api_logger)

        if landing_ok:
            await snapshot_cookies_cdp(tab, api_logger, "03_after_landing_check_availability")
            api_logger.set_phase("redirect:waiting_for_buy_page")
            for _ in range(30):
                url = tab.target.url or ""
                if "/buy" in url:
                    print("  Redirected to buy page")
                    break
                await asyncio.sleep(0.5)
            else:
                print("  No redirect to /buy — checking current page")
        else:
            print("  Landing page blocked — navigating to /buy directly")
            api_logger.set_phase("fallback:direct_buy_page")
            await tab.get("https://frontier.com/buy")

        await asyncio.sleep(random.uniform(2.0, 4.0))
        await snapshot_cookies_cdp(tab, api_logger, "04_after_buy_page_load")

        current_url = tab.target.url or ""
        if "/buy" in current_url:
            await enter_address_buy_page(tab, api_logger)
            await snapshot_cookies_cdp(tab, api_logger, "05_after_buy_page_check")

        api_logger.set_phase("plans_page:loading")
        await asyncio.sleep(random.uniform(3.0, 6.0))
        await snapshot_cookies_cdp(tab, api_logger, "06_after_plans_loaded")

        await browse_plans(tab, api_logger)
        await snapshot_cookies_cdp(tab, api_logger, "07_after_browsing_plans")

        print("\nDone. Closing browser.")
    except Exception as exc:
        print(f"\nERROR during automation: {exc}")
        await snapshot_cookies_cdp(tab, api_logger, "99_after_error")
    finally:
        await asyncio.sleep(1)
        os.makedirs(LOGS_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        full_path = os.path.join(LOGS_DIR, f"{LEVEL_NAME}_{ts}.xlsx")
        api_logger.save_to_excel(full_path)

        filtered_path = os.path.join(LOGS_DIR, f"{LEVEL_NAME}_filtered.xlsx")
        kept = filter_excel(full_path, filtered_path)
        print(f"Filtered to {kept} important calls -> {filtered_path}")

        browser.stop()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Level 5: Frontier automation with nodriver (raw CDP)"
    )
    parser.add_argument("--proxy", type=str, default=None,
                        help="Proxy URL, e.g. http://user:pass@host:port")
    args = parser.parse_args()

    uc.loop().run_until_complete(run(proxy=args.proxy))


if __name__ == "__main__":
    main()
