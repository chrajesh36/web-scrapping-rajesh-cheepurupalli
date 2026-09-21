"""Frontier batch address checker — anti-detection hardened.

Each address gets its OWN fresh browser session (new cookies, new _abck,
new TLS session, new fingerprint). This prevents Akamai from correlating
multiple address checks into a single suspicious session.

Usage:
    python frontier_batch_stealth.py                    # all 50 addresses
    python frontier_batch_stealth.py --max 10           # first 10 only
    python frontier_batch_stealth.py --skip-cached      # skip already-checked
    python frontier_batch_stealth.py --proxy URL        # use proxy
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
from dataclasses import dataclass, field
from datetime import datetime

import nodriver as uc

from behavior import (
    async_bezier_mouse_move,
    async_lognormal_type,
)

FRONTIER_BUY = "https://frontier.com/buy"
WARMUP_URL = "https://frontier.com/why-frontier"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOGS_DIR = os.path.join(BASE_DIR, "logs", "frontier")
ADDRESSES_FILE = os.path.join(BASE_DIR, "frontier_addresses.json")
RESULTS_FILE = os.path.join(BASE_DIR, "frontier_address_scopes.json")


@dataclass
class AddressResult:
    address: str
    state: str
    market: str
    scope: str
    reason: str
    num_offers: int = 0
    offer_names: list[str] = field(default_factory=list)
    final_url: str = ""
    elapsed_s: float = 0.0


def load_addresses() -> list[dict]:
    with open(ADDRESSES_FILE) as f:
        return json.load(f)["addresses"]


def load_existing() -> dict[str, dict]:
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            return {r["address"]: r for r in json.load(f).get("results", [])}
    return {}


def save_results(all_results: dict[str, dict]) -> None:
    output = {
        "last_updated": datetime.now().isoformat(),
        "total": len(all_results),
        "results": list(all_results.values()),
    }
    with open(RESULTS_FILE, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)


# ── Warm-up browsing ─────────────────────────────────────────────────────

async def warmup(tab, duration_s: float = 20.0) -> None:
    """Natural browsing warm-up to build behavioral baseline."""
    start = time.time()
    vw = await tab.evaluate("window.innerWidth") or 1440
    vh = await tab.evaluate("window.innerHeight") or 900
    while time.time() - start < duration_s:
        action = random.choices(
            ["scroll", "move", "hover", "pause", "scroll_up"],
            weights=[30, 25, 20, 15, 10],
        )[0]
        if action == "scroll":
            await tab.scroll_down(random.randint(150, 500))
            await asyncio.sleep(random.uniform(0.8, 2.0))
        elif action == "move":
            cx = await tab.evaluate("window._bhvX || window.innerWidth/2")
            cy = await tab.evaluate("window._bhvY || window.innerHeight/2")
            await async_bezier_mouse_move(tab, cx, cy,
                                          random.uniform(80, vw - 80),
                                          random.uniform(80, vh - 80), steps=18)
            await asyncio.sleep(random.uniform(0.3, 1.0))
        elif action == "hover":
            try:
                links = await tab.query_selector_all("nav a, header a")
                if links:
                    link = random.choice(links[:8])
                    pos = await link.get_position()
                    if pos:
                        cx = await tab.evaluate("window._bhvX || window.innerWidth/2")
                        cy = await tab.evaluate("window._bhvY || window.innerHeight/2")
                        await async_bezier_mouse_move(tab, cx, cy, pos.x, pos.y, steps=15)
                        await asyncio.sleep(random.uniform(0.4, 1.2))
            except Exception:
                await asyncio.sleep(0.5)
        elif action == "scroll_up":
            await tab.scroll_up(random.randint(100, 300))
            await asyncio.sleep(random.uniform(0.5, 1.5))
        else:
            await asyncio.sleep(random.uniform(1.0, 2.5))


async def dismiss_banner(tab) -> None:
    for text in ["Close", "Accept All"]:
        try:
            btn = await tab.find(text, timeout=2)
            if btn:
                await btn.click()
                await asyncio.sleep(0.5)
                return
        except Exception:
            continue


# ── Single address check in a FRESH browser ──────────────────────────────

async def check_address(address: str, state: str, market: str,
                        proxy: str | None = None) -> AddressResult:
    """Check one address using a fresh browser session."""
    start = time.time()
    result = AddressResult(address=address, state=state, market=market,
                           scope="UNKNOWN", reason="")

    tmp_dir = tempfile.mkdtemp(prefix="frontier_")
    browser_args = []
    if proxy:
        browser_args.append(f"--proxy-server={proxy}")

    try:
        browser = await uc.start(
            headless=False,
            user_data_dir=tmp_dir,
            browser_args=browser_args or None,
        )

        # Phase 1: Warm-up on non-protected page
        tab = await browser.get(WARMUP_URL)
        await asyncio.sleep(random.uniform(3.0, 5.0))
        await dismiss_banner(tab)
        await warmup(tab, duration_s=random.uniform(15.0, 25.0))

        # Phase 2: Navigate to /buy and warm-up
        await tab.get(FRONTIER_BUY)
        await asyncio.sleep(random.uniform(3.0, 5.0))
        await dismiss_banner(tab)
        await tab.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5)
        await warmup(tab, duration_s=random.uniform(10.0, 15.0))

        # Scroll back to top for address input
        await tab.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1)

        # Phase 3: Find and fill address
        field = await tab.query_selector("#street-address")
        if not field:
            field = await tab.query_selector("input.address-form__input")
        if not field:
            result.scope = "INVALID_ADDRESS"
            result.reason = "Address field not found"
            browser.stop()
            return result

        # Clear with React-safe setter
        await tab.evaluate("""
            (() => {
                const input = document.querySelector('#street-address');
                if (input) {
                    input.focus();
                    const s = Object.getOwnPropertyDescriptor(
                        HTMLInputElement.prototype, 'value'
                    ).set;
                    s.call(input, '');
                    input.dispatchEvent(new Event('input', {bubbles: true}));
                }
            })()
        """)
        await asyncio.sleep(0.3)
        await field.click()
        await asyncio.sleep(0.3)

        # Type address with natural cadence
        await async_lognormal_type(tab, field, address)
        await asyncio.sleep(random.uniform(1.5, 3.0))

        # Select first autocomplete option
        try:
            opts = await tab.query_selector_all("[role='option']")
            if opts:
                await asyncio.sleep(random.uniform(0.3, 0.8))
                await opts[0].click()
            else:
                city = address.split(",")[1].strip().split()[0] if "," in address else ""
                if city:
                    opt = await tab.find(city, timeout=3)
                    if opt:
                        await opt.click()
        except Exception:
            pass

        await asyncio.sleep(random.uniform(0.5, 1.5))

        # Click CHECK AVAILABILITY via JS
        clicked = await tab.evaluate("""
            (() => {
                const btns = document.querySelectorAll('button');
                for (const b of btns) {
                    if (b.innerText && b.innerText.toLowerCase().includes('check availability')) {
                        b.click(); return true;
                    }
                }
                return false;
            })()
        """)
        if not clicked:
            result.scope = "INVALID_ADDRESS"
            result.reason = "CHECK AVAILABILITY button not found"
            browser.stop()
            return result

        # Wait for result
        await asyncio.sleep(random.uniform(6.0, 10.0))

        # Phase 4: Determine scope
        final_url = await tab.evaluate("location.href") or ""
        result.final_url = final_url

        if "allconnect.com" in final_url:
            result.scope = "PROVIDER_NOT_AVAILABLE"
            result.reason = "Redirected to allconnect.com — Frontier not available"

        elif "frontier.com" in final_url:
            page_text = await tab.evaluate("document.body.innerText") or ""
            if not isinstance(page_text, str):
                page_text = str(page_text)

            has_pricing = bool(re.search(r'\$\d+', page_text))
            has_plans = any(kw in page_text.lower() for kw in [
                "view plan", "add to cart", "shop now", "/mo", "per mo"
            ])
            page_lower = page_text.lower()

            if "technical difficulties" in page_lower:
                result.scope = "PROVIDER_NOT_AVAILABLE"
                result.reason = "Technical difficulties error"
            elif "already a frontier customer" in page_lower or "current customer" in page_lower:
                result.scope = "CURRENT_CUSTOMER"
                result.reason = "Existing customer detected"
            elif "isn't available" in page_lower or "not available at your address" in page_lower:
                result.scope = "PROVIDER_NOT_AVAILABLE"
                result.reason = "Frontier not available at this address"
            elif has_pricing and has_plans:
                result.scope = "PROSPECT_CUSTOMER"
                result.reason = "Plans with pricing found"
                # Extract plan names
                try:
                    plans_raw = await tab.evaluate("""
                        JSON.stringify((() => {
                            const names = [];
                            document.querySelectorAll('h2, h3, h4').forEach(el => {
                                const t = el.innerText.trim();
                                if (t.match(/fiber|gig|internet/i) && t.length < 80) names.push(t);
                            });
                            return names;
                        })())
                    """)
                    result.offer_names = json.loads(plans_raw) if isinstance(plans_raw, str) else []
                    result.num_offers = len(result.offer_names) or 1
                except Exception:
                    pass
            elif "enter your address" in page_lower and not has_pricing:
                result.scope = "PROVIDER_NOT_AVAILABLE"
                result.reason = "Plans did not load after address submission"
            else:
                result.scope = "PROVIDER_NOT_AVAILABLE"
                result.reason = "No pricing or plans detected"
        else:
            result.scope = "PROVIDER_NOT_AVAILABLE"
            result.reason = f"Unexpected redirect: {final_url[:60]}"

        browser.stop()

    except Exception as exc:
        result.scope = "INVALID_ADDRESS"
        result.reason = f"Error: {str(exc)[:80]}"
        try:
            browser.stop()
        except Exception:
            pass

    result.elapsed_s = time.time() - start
    return result


# ── Main batch runner ────────────────────────────────────────────────────

async def run_batch(max_addr: int | None = None, skip_cached: bool = False,
                    proxy: str | None = None) -> list[AddressResult]:
    all_addrs = load_addresses()
    existing = load_existing() if skip_cached else {}

    to_check = [a for a in all_addrs if a["address"] not in existing]
    if max_addr:
        to_check = to_check[:max_addr]

    print(f"\n{'='*70}")
    print(f"  Frontier Stealth Batch Checker")
    print(f"  {len(to_check)} addresses | fresh browser per address")
    print(f"  proxy={'yes' if proxy else 'none'}")
    print(f"{'='*70}\n")

    results = []
    merged = dict(existing)

    for i, entry in enumerate(to_check):
        addr = entry["address"]
        state = entry.get("state", "")
        market = entry.get("market", "")
        print(f"  [{i+1}/{len(to_check)}] {addr}")

        try:
            r = await asyncio.wait_for(
                check_address(addr, state, market, proxy),
                timeout=120.0,
            )
        except asyncio.TimeoutError:
            r = AddressResult(address=addr, state=state, market=market,
                              scope="INVALID_ADDRESS",
                              reason="Hard timeout (120s)", elapsed_s=120.0)

        icon = {"PROSPECT_CUSTOMER": "✅", "CURRENT_CUSTOMER": "🔵",
                "PROVIDER_NOT_AVAILABLE": "❌", "INVALID_ADDRESS": "⚠️"}.get(r.scope, "❓")
        print(f"         {icon} {r.scope} ({r.elapsed_s:.0f}s) — {r.reason[:60]}")

        results.append(r)
        merged[addr] = {
            "address": addr, "state": state, "market": market,
            "scope": r.scope, "reason": r.reason,
            "num_offers": r.num_offers, "offer_names": r.offer_names,
            "final_url": r.final_url, "last_checked": datetime.now().isoformat(),
        }

        # Save after each address
        save_results(merged)

        # Random cool-down between addresses (30s–90s)
        if i < len(to_check) - 1:
            cooldown = random.uniform(30, 90)
            print(f"         💤 cooling down {cooldown:.0f}s before next address...")
            await asyncio.sleep(cooldown)

    return results


def print_summary(results: list[AddressResult]) -> None:
    print(f"\n\n{'='*120}")
    print(f"  RESULTS — {len(results)} addresses")
    print(f"{'='*120}")
    print(f"{'#':>3} {'State':>5} {'Scope':<26} {'Time':>5} {'Address':<50} {'Reason'}")
    print(f"{'─'*3} {'─'*5} {'─'*26} {'─'*5} {'─'*50} {'─'*50}")

    for i, r in enumerate(results):
        icon = {"PROSPECT_CUSTOMER": "✅", "CURRENT_CUSTOMER": "🔵",
                "PROVIDER_NOT_AVAILABLE": "❌", "INVALID_ADDRESS": "⚠️"}.get(r.scope, "❓")
        print(f"{i+1:>3} {r.state:>5} {icon} {r.scope:<24} {r.elapsed_s:>4.0f}s {r.address:<50} {r.reason[:50]}")

    from collections import Counter
    counts = Counter(r.scope for r in results)
    print(f"\n  Totals:")
    for scope, count in counts.most_common():
        print(f"    {scope}: {count}")


def main():
    parser = argparse.ArgumentParser(description="Frontier stealth batch checker")
    parser.add_argument("--max", type=int, default=None, help="Max addresses to check")
    parser.add_argument("--address", type=str, default=None,
                        help="Check a single address, e.g. '1308 Chase St, Novato, CA 94945'")
    parser.add_argument("--skip-cached", action="store_true", help="Skip already-checked addresses")
    parser.add_argument("--proxy", type=str, default=None, help="Proxy URL")
    args = parser.parse_args()

    if args.address:
        addr = args.address.strip()
        state = ""
        parts = [p.strip() for p in addr.split(",")]
        if len(parts) >= 2:
            last = parts[-1].split()
            if last:
                state = last[0] if len(last[0]) == 2 else (parts[-2].split()[-1] if len(parts) >= 2 else "")
        async def _one():
            print(f"\n  Checking: {addr}")
            r = await asyncio.wait_for(
                check_address(addr, state or "??", "manual", args.proxy),
                timeout=120.0,
            )
            return [r]
        results = uc.loop().run_until_complete(_one())
        existing = load_existing()
        for r in results:
            existing[r.address] = {
                "address": r.address, "state": r.state, "market": r.market,
                "scope": r.scope, "reason": r.reason,
                "num_offers": r.num_offers, "offer_names": r.offer_names,
                "final_url": r.final_url, "last_checked": datetime.now().isoformat(),
            }
        save_results(existing)
    else:
        results = uc.loop().run_until_complete(
            run_batch(max_addr=args.max, skip_cached=args.skip_cached, proxy=args.proxy)
        )
    print_summary(results)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(LOGS_DIR, f"stealth_batch_{ts}.json")
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(log_path, "w") as f:
        json.dump({"results": [{"address": r.address, "state": r.state, "scope": r.scope,
                                 "reason": r.reason, "elapsed_s": r.elapsed_s} for r in results]},
                  f, indent=2)
    print(f"\n  Log → {log_path}")
    print(f"  Scopes → {RESULTS_FILE}")


if __name__ == "__main__":
    main()
