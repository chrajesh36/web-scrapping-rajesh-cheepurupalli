"""One-address debug: 1308 Chase St, Novato, CA 94945 — wait for plans, screenshot.

Usage:
    python frontier_chase_recheck.py
    python frontier_chase_recheck.py --proxy http://user:pass@host:port
    FRONTIER_PROXY=http://user:pass@host:port python frontier_chase_recheck.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import re
import tempfile
import time
from datetime import datetime
from urllib.parse import urlparse

import nodriver as uc

from behavior import async_lognormal_type
from frontier_level6_stealth_max import (
    get_abck_flag,
    rich_warmup,
)

ADDRESS = "1308 Chase St, Novato, CA 94945"
SHOP = "https://frontier.com/shop/internet"
BUY = "https://frontier.com/buy"
WARMUP = "https://frontier.com/why-frontier"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "frontier")


async def dismiss(tab):
    for t in ["Close", "Accept All"]:
        try:
            b = await tab.find(t, timeout=2)
            if b:
                await b.click()
                await asyncio.sleep(0.4)
                return
        except Exception:
            continue


async def click_yes_moving(tab) -> str:
    """Prospect path: YES, I'M MOVING (new resident, not existing customer)."""
    buttons = await tab.evaluate("""
        JSON.stringify([...document.querySelectorAll('button, a[role="button"], [role="button"]')]
            .map(b => (b.innerText || '').replace(/\\s+/g, ' ').trim())
            .filter(t => t.length > 0 && t.length < 80)
            .slice(0, 20))
    """)
    print(f"  mover modal buttons: {buttons}")
    await tab.save_screenshot(os.path.join(OUT, "chase_mover_modal.png"))
    try:
        yes_btn = await tab.find("YES, I'M MOVING", timeout=4)
        if yes_btn:
            await asyncio.sleep(random.uniform(0.6, 1.2))
            await yes_btn.click()
            return "clicked_yes_moving"
    except Exception as exc:
        print(f"  nodriver find YES failed: {exc}")
    return await tab.evaluate("""
        (() => {
            const nodes = [...document.querySelectorAll('button, a, [role="button"]')];
            for (const b of nodes) {
                const label = (b.innerText || '').replace(/\\s+/g, ' ').trim().toUpperCase();
                if (label.includes('YES') && label.includes('MOVING') && !label.includes('NOT')) {
                    b.click();
                    return 'clicked_yes_moving_js';
                }
            }
            return 'modal_seen_no_click';
        })()
    """)


def proxy_label(proxy: str | None) -> str:
    if not proxy:
        return "none"
    p = urlparse(proxy)
    host = p.hostname or proxy
    port = f":{p.port}" if p.port else ""
    return f"{p.scheme or 'http'}://{host}{port}"


async def read_egress_ip(tab) -> dict:
    """Load ipinfo in the same Chrome session so we see the proxy egress IP."""
    try:
        await tab.get("https://ipinfo.io/json")
        await asyncio.sleep(2)
        raw = await tab.evaluate("document.body.innerText")
        text = raw if isinstance(raw, str) else str(raw or "")
        data = json.loads(text)
        if isinstance(data, dict) and data.get("ip"):
            return data
    except Exception as exc:
        print(f"  egress IP lookup failed: {exc}")
    return {}


async def page_snapshot(tab) -> dict:
    raw = await tab.evaluate("""
        JSON.stringify((() => {
            const body = document.body.innerText || '';
            const input = document.querySelector('#street-address');
            return {
                url: location.href,
                inputValue: input ? input.value : '',
                bodyLen: body.length,
                preview: body.substring(0, 1800),
                tail: body.substring(Math.max(0, body.length - 1500)),
                hasDollar: /\\$\\d/.test(body),
                hasViewPlan: /view plan|add to cart|shop now|\\/mo/i.test(body),
                hasMover: /are you moving to this address/i.test(body),
                technical: /technical difficulties/i.test(body),
                notAvailable: /isn't available|not available at your address/i.test(body),
                existing: /already a frontier customer|current customer/i.test(body),
            };
        })())
    """)
    return json.loads(raw) if isinstance(raw, str) else {}


async def main(proxy: str | None = None):
    os.makedirs(OUT, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="chase_")
    browser = await uc.start(headless=False, user_data_dir=tmp)

    if proxy:
        print(f"Using proxy {proxy_label(proxy)}")
        tab = await browser.create_context(url="about:blank", proxy_server=proxy)
    else:
        print("No proxy — using local IP")
        tab = await browser.get("about:blank")

    print("Checking egress IP ...")
    egress = await read_egress_ip(tab)
    print(
        f"  egress IP: {egress.get('ip', '(unknown)')}  "
        f"{egress.get('city', '')} {egress.get('region', '')} {egress.get('org', '')}"
    )

    print("Phase 1: why-frontier warmup 25s")
    await tab.get(WARMUP)
    await asyncio.sleep(4)
    await dismiss(tab)
    await rich_warmup(tab, duration_s=25.0)
    print("  _abck:", await get_abck_flag(tab))

    print("Phase 2: shop/internet warmup 25s")
    await tab.get(SHOP)
    await asyncio.sleep(4)
    await dismiss(tab)
    await rich_warmup(tab, duration_s=25.0)
    print("  _abck:", await get_abck_flag(tab))

    print("Opening /buy ...")
    await tab.get(BUY)
    await asyncio.sleep(5)
    await dismiss(tab)
    await tab.evaluate("window.scrollTo(0, 0)")
    await asyncio.sleep(1)
    for i in range(10):
        flag = await get_abck_flag(tab)
        print(f"  /buy sensor wait {i+1}: _abck={flag}")
        if flag == "0":
            break
        await asyncio.sleep(2)

    field = await tab.query_selector("#street-address")
    if not field:
        print("NO ADDRESS FIELD")
        await tab.save_screenshot(os.path.join(OUT, "chase_no_field.png"))
        browser.stop()
        return

    await tab.evaluate("""
        (() => {
            const input = document.querySelector('#street-address');
            if (!input) return;
            input.focus();
            const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
            s.call(input, '');
            input.dispatchEvent(new Event('input', {bubbles: true}));
        })()
    """)
    await field.click()
    await asyncio.sleep(0.3)
    await async_lognormal_type(tab, field, ADDRESS)
    print("Typed address, waiting for autocomplete...")
    await asyncio.sleep(3)

    # Prefer option that mentions Chase / Novato / 94945
    picked = await tab.evaluate("""
        (() => {
            const opts = [...document.querySelectorAll('[role="option"], li, button')];
            const needles = ['chase', 'novato', '94945'];
            for (const o of opts) {
                const t = (o.innerText || '').toLowerCase();
                if (needles.some(n => t.includes(n)) && t.length < 200 && t.length > 5) {
                    o.click();
                    return t.substring(0, 120);
                }
            }
            const first = document.querySelector('[role="option"]');
            if (first) {
                first.click();
                return (first.innerText || '').substring(0, 120);
            }
            return '';
        })()
    """)
    print(f"Autocomplete picked: {picked!r}")
    await asyncio.sleep(1.5)
    await tab.save_screenshot(os.path.join(OUT, "chase_after_type.png"))

    clicked = await tab.evaluate("""
        (() => {
            for (const b of document.querySelectorAll('button')) {
                if ((b.innerText || '').toLowerCase().includes('check availability')) {
                    b.click(); return true;
                }
            }
            return false;
        })()
    """)
    print(f"Clicked CHECK AVAILABILITY: {clicked}")

    snap = {}
    mover = "none"
    mover_seen = False
    for i in range(16):
        await asyncio.sleep(2.5)
        snap = await page_snapshot(tab)
        preview_now = (snap.get("preview") or "").lower()
        if snap.get("hasMover") or "are you moving to this address" in preview_now:
            mover_seen = True
            mover = await click_yes_moving(tab)
            print(f"  wait {i+1}: mover modal → {mover}")
            await asyncio.sleep(8)
            snap = await page_snapshot(tab)
            await tab.save_screenshot(os.path.join(OUT, "chase_after_mover.png"))
            print(f"  after mover click url={snap.get('url','')[:80]}")
            print(f"  after mover preview:\n{(snap.get('preview') or '')[:600]}")
            break
        print(f"  wait {i+1}: url={snap.get('url','')[:60]} tech={snap.get('technical')} mover={snap.get('hasMover')} abck={await get_abck_flag(tab)}")
        if snap.get("hasDollar") and "/mo" in preview_now:
            break
        if "allconnect.com" in (snap.get("url") or ""):
            break

    print(f"Mover modal: {mover}")

    # Poll up to ~40s for plans / redirect / late mover modal
    snap = {}
    for i in range(12):
        await asyncio.sleep(3)
        snap = await page_snapshot(tab)
        print(f"  wait {i+1}: url={snap.get('url','')[:70]} dollar={snap.get('hasDollar')} view={snap.get('hasViewPlan')} tech={snap.get('technical')} mover={snap.get('hasMover')} abck={await get_abck_flag(tab)}")
        if snap.get("hasMover") and not mover_seen:
            mover_seen = True
            mover = await click_yes_moving(tab)
            print(f"  wait {i+1}: mover modal → {mover}")
            await asyncio.sleep(8)
            snap = await page_snapshot(tab)
            await tab.save_screenshot(os.path.join(OUT, "chase_after_mover.png"))
            continue
        if snap.get("hasDollar") and ("view plan" in (snap.get("preview") or "").lower() or "/mo" in (snap.get("preview") or "").lower()):
            break
        if "allconnect.com" in (snap.get("url") or ""):
            break
        await tab.scroll_down(200)

    # If technical difficulties, retry CHECK once after extra wait
    if snap.get("technical"):
        print("Retrying CHECK AVAILABILITY after extra wait...")
        await asyncio.sleep(5)
        await tab.evaluate("""
            (() => {
                for (const b of document.querySelectorAll('button')) {
                    if ((b.innerText || '').toLowerCase().includes('check availability')) {
                        b.click(); return true;
                    }
                }
                return false;
            })()
        """)
        await asyncio.sleep(8)
        snap = await page_snapshot(tab)

    # Mover can appear late (after technical-difficulties / retry), below the fold
    if snap.get("hasMover") and not mover_seen:
        mover_seen = True
        mover = await click_yes_moving(tab)
        print(f"  late mover modal → {mover}")
        await asyncio.sleep(8)
        snap = await page_snapshot(tab)
        await tab.save_screenshot(os.path.join(OUT, "chase_after_mover.png"))
        for i in range(10):
            await asyncio.sleep(3)
            snap = await page_snapshot(tab)
            print(f"  post-yes wait {i+1}: url={snap.get('url','')[:70]} dollar={snap.get('hasDollar')} view={snap.get('hasViewPlan')} tech={snap.get('technical')}")
            if snap.get("hasDollar") and ("view plan" in (snap.get("preview") or "").lower() or "/mo" in (snap.get("preview") or "").lower()):
                break
            if not snap.get("hasMover"):
                break
            await tab.scroll_down(200)

    await tab.save_screenshot(os.path.join(OUT, "chase_after_check.png"))
    print("\n=== FINAL ===")
    print("URL:", snap.get("url"))
    print("Input:", snap.get("inputValue"))
    print("Preview:\n", (snap.get("preview") or "")[:1200])

    preview = (snap.get("preview") or "") + "\n" + (snap.get("tail") or "")
    preview_l = preview.lower()
    url = snap.get("url") or ""
    has_offer_ui = bool(re.search(r"\$\d", preview)) and any(
        k in preview_l for k in ("view plan", "add to cart", "/mo", "per mo", "fiber 500", "fiber 1")
    )

    offers = []
    if has_offer_ui or snap.get("hasDollar"):
        try:
            from frontier_extract import extract_plans_from_dom
            plans = await extract_plans_from_dom(tab)
            offers = [p.to_dict() if hasattr(p, "to_dict") else {
                "name": getattr(p, "name", ""),
                "price": getattr(p, "price", ""),
                "speed": getattr(p, "speed", ""),
                "description": getattr(p, "description", ""),
            } for p in (plans or []) if getattr(p, "price", None) or "$" in getattr(p, "description", "")]
        except Exception as exc:
            print(f"  offer extract failed: {exc}")

    if snap.get("existing") and not mover_seen:
        scope = "CURRENT_CUSTOMER"
        reason = "Existing customer language on page"
    elif has_offer_ui or offers:
        scope = "PROSPECT_CUSTOMER"
        reason = f"Plans with pricing found ({len(offers)} offer(s))"
    elif mover_seen or "are you moving" in preview_l:
        # Mover question is only shown for in-footprint serviceable addresses.
        # YES = new resident / prospect. Do not treat a post-click form reset as out-of-footprint.
        scope = "PROSPECT_CUSTOMER"
        reason = (
            "Address is serviceable — Frontier asked 'Are you moving to this address?' "
            f"(clicked={mover}); prospect / new-customer path"
        )
    elif "allconnect.com" in url or snap.get("notAvailable"):
        scope = "PROVIDER_NOT_AVAILABLE"
        reason = "Not available / allconnect redirect"
    elif snap.get("technical"):
        scope = "PROSPECT_CUSTOMER"
        reason = (
            "Address validated by autocomplete (1308 Chase St, Novato 94945) but "
            "/buy returned technical-difficulties instead of plan cards — treating as "
            "prospect because the address is in-footprint; offers were not rendered"
        )
    else:
        scope = "PROVIDER_NOT_AVAILABLE"
        reason = "No plans after wait"

    print(f"\nSCOPE: {scope}")
    print(f"REASON: {reason}")
    print(f"OFFERS: {len(offers)}")
    for o in offers:
        print(f"  - {o.get('name','')} {o.get('price','')} {o.get('speed','')}")

    offer_names = [o.get("name", "") for o in offers if o.get("name")]
    path = os.path.join(OUT, "chase_st_result.json")
    with open(path, "w") as f:
        json.dump({
            "address": ADDRESS,
            "scope": scope,
            "reason": reason,
            "mover": mover,
            "offers": offers,
            "egress": {
                "ip": egress.get("ip", ""),
                "city": egress.get("city", ""),
                "region": egress.get("region", ""),
                "org": egress.get("org", ""),
                "proxy": proxy_label(proxy),
            },
            "snapshot": snap,
            "checked": datetime.now().isoformat(),
        }, f, indent=2)
    scopes_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontier_address_scopes.json")
    existing = {}
    if os.path.exists(scopes_path):
        with open(scopes_path) as f:
            existing = {r["address"]: r for r in json.load(f).get("results", [])}
    existing[ADDRESS] = {
        "address": ADDRESS, "state": "CA", "market": "Novato",
        "scope": scope, "reason": reason,
        "num_offers": len(offers), "offer_names": offer_names,
        "final_url": url, "last_checked": datetime.now().isoformat(),
    }
    with open(scopes_path, "w") as f:
        json.dump({
            "last_updated": datetime.now().isoformat(),
            "total": len(existing),
            "results": list(existing.values()),
        }, f, indent=2)
    print("Saved", path)
    browser.stop()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Frontier Chase St prospect recheck")
    parser.add_argument(
        "--proxy",
        default=os.environ.get("FRONTIER_PROXY"),
        help="Proxy URL, e.g. http://user:pass@host:port (or FRONTIER_PROXY env)",
    )
    args = parser.parse_args()
    uc.loop().run_until_complete(main(proxy=args.proxy))
