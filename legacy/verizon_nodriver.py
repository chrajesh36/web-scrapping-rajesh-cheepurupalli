"""Level 5: Verizon broadband-plans automation using nodriver.

nodriver connects to Chrome via raw CDP — zero automation fingerprint
because there is no Playwright CDP handshake sequence. Combined with:
  - behavior.py async Bezier mouse / log-normal typing
  - Homepage warm-up browsing (15 s)
  - CDP-based network interception for api_logger compatibility

Usage:
    python verizon_nodriver.py [--proxy URL]
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
import nodriver.cdp.storage as storage
import openpyxl

from api_logger import (
    ApiCallRecord,
    ApiLogger,
    CookieSnapshotRow,
    VENDOR_SIGNATURES,
    KNOWN_BOT_COOKIE_HINTS,
    _clean,
    _pretty,
    _is_randomized_sensor_path,
    _matches_any,
)
from behavior import (
    async_bezier_click,
    async_bezier_mouse_move,
    async_lognormal_type,
    async_warmup_browse,
    lognormal_delay,
    reading_pause,
)

VERIZON_URL = "https://www.verizon.com/home/internet/"
ADDRESS = "140 West Street, New York, NY 10007"
LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LEVEL_NAME = "level5_nodriver"


class CdpNetworkLogger:
    """Captures network traffic via CDP events and populates an ApiLogger."""

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
    """Take a cookie snapshot using CDP Storage.getCookies."""
    try:
        cookies = await tab.send(storage.get_cookies())
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
    for text in ["Accept All", "Accept all", "Close"]:
        try:
            btn = await tab.find(text, timeout=2)
            if btn:
                await btn.click()
                await asyncio.sleep(0.5)
                return
        except Exception:
            continue


async def enter_address_and_submit(tab, api_logger: ApiLogger) -> None:
    print("Entering service address...")
    api_logger.set_phase("address_entry:typing")

    address_field = None
    for selector in ["#streetaddress", "input[aria-label*='Street Address']"]:
        try:
            address_field = await tab.query_selector(selector)
            if address_field:
                break
        except Exception:
            continue

    if not address_field:
        try:
            address_field = await tab.find("Street Address", timeout=10)
        except Exception:
            pass

    if not address_field:
        raise RuntimeError("Could not find address input field")

    await address_field.click()
    await address_field.clear_input()
    await async_lognormal_type(tab, address_field, ADDRESS)
    await asyncio.sleep(random.uniform(1.0, 2.5))

    api_logger.set_phase("address_entry:autocomplete_suggestions")
    try:
        suggestion = await tab.find("140 West", timeout=5)
        if suggestion:
            await asyncio.sleep(random.uniform(0.5, 1.5))
            await suggestion.click()
            print("  selected suggestion")
        else:
            print("  no autocomplete suggestion found")
            await address_field.send_keys("\n")
    except Exception:
        print("  no autocomplete, pressing Enter")
        await address_field.send_keys("\n")

    await asyncio.sleep(random.uniform(0.8, 2.0))

    api_logger.set_phase("address_entry:get_started_click")
    try:
        get_started = await tab.find("Get started", timeout=10)
        if get_started:
            await asyncio.sleep(random.uniform(0.3, 1.0))
            await get_started.click()
            print("  clicked 'Get started'")
    except Exception as exc:
        print(f"  'Get started' click failed: {exc}")

    api_logger.set_phase("address_entry:business_residential_modal")
    try:
        residential = await tab.find("Continue as residential", timeout=6)
        if residential:
            await asyncio.sleep(random.uniform(0.5, 1.5))
            await residential.click()
            print("  selected 'Continue as residential'")
    except Exception:
        pass


async def wait_for_offers_page(tab, api_logger: ApiLogger) -> None:
    print("Waiting for plans to load...")
    api_logger.set_phase("offers_page:loading")

    for _ in range(60):
        url = tab.target.url or ""
        if "inhome/buildproducts" in url:
            break
        await asyncio.sleep(0.5)
    else:
        print("  WARNING: did not navigate to offers page")

    try:
        await tab.find("Review details", timeout=30)
    except Exception:
        pass

    await asyncio.sleep(random.uniform(2.0, 4.0))
    await dismiss_cookie_banner(tab)


async def click_each_plan(tab, api_logger: ApiLogger) -> None:
    try:
        buttons = await tab.find_all("Review details")
    except Exception:
        buttons = []
    total = len(buttons)
    if total == 0:
        print("  WARNING: No 'Review details' buttons found.")
        return
    print(f"Found {total} plan(s) on the offers page.")

    for index, btn in enumerate(buttons):
        print(f"\n  Opening plan {index + 1}/{total}...")
        api_logger.set_phase(f"plan_review:{index + 1}_of_{total}")
        try:
            await btn.scroll_into_view()
            await asyncio.sleep(random.uniform(1.0, 3.0))
            await btn.click()
            await asyncio.sleep(random.uniform(1.5, 3.0))
            await close_details_modal(tab)
            print(f"  opened and closed plan {index + 1}")
        except Exception as exc:
            print(f"  could not open plan {index + 1}: {exc}")
            await close_details_modal(tab)
        await asyncio.sleep(random.uniform(1.0, 2.5))


async def close_details_modal(tab) -> None:
    for text in ["Close"]:
        try:
            btn = await tab.find(text, timeout=2)
            if btn:
                await btn.click()
                await asyncio.sleep(0.5)
                return
        except Exception:
            continue
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
    rows_to_delete = []
    for row_idx in range(ws.max_row, 1, -1):
        level = ws.cell(row=row_idx, column=9).value
        if level in ("None", "Low"):
            rows_to_delete.append(row_idx)
    for row_idx in rows_to_delete:
        ws.delete_rows(row_idx, 1)
    wb.save(dst_path)
    return ws.max_row - 1


async def run(proxy: str | None = None) -> None:
    print(f"\n{'='*60}")
    print(f"  LEVEL 5: nodriver (raw CDP, zero automation artifacts)")
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

    tab = await browser.get(VERIZON_URL)

    api_logger = ApiLogger()
    cdp_logger = CdpNetworkLogger(api_logger)
    await cdp_logger.enable(tab)

    try:
        print(f"Opened {VERIZON_URL}")
        api_logger.set_phase("landing_page:initial_load")
        await asyncio.sleep(random.uniform(3.0, 5.0))

        await snapshot_cookies_cdp(tab, api_logger, "01_after_landing_page_load")
        await dismiss_cookie_banner(tab)

        print("Warm-up browsing for ~15 seconds...")
        api_logger.set_phase("warmup:browsing")
        await async_warmup_browse(tab, duration_s=15.0)
        await snapshot_cookies_cdp(tab, api_logger, "02_after_warmup_browse")

        await enter_address_and_submit(tab, api_logger)
        await snapshot_cookies_cdp(tab, api_logger, "03_after_get_started_click")

        await wait_for_offers_page(tab, api_logger)
        await snapshot_cookies_cdp(tab, api_logger, "04_after_offers_page_loaded")

        await click_each_plan(tab, api_logger)
        await snapshot_cookies_cdp(tab, api_logger, "05_after_all_plans_reviewed")
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
        description="Level 5: Verizon automation with nodriver (raw CDP)"
    )
    parser.add_argument("--proxy", type=str, default=None,
                        help="Proxy URL, e.g. http://user:pass@host:port")
    args = parser.parse_args()

    uc.loop().run_until_complete(run(proxy=args.proxy))


if __name__ == "__main__":
    main()
