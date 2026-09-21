"""Batch Frontier address checker — run multiple addresses in one session.

Uses Level 6 stealth (nodriver) with a single warm-up phase, then cycles
through addresses, recording scope and offers for each.

Usage:
    python frontier_batch_extract.py
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime

import nodriver as uc
import nodriver.cdp.network as net
import nodriver.cdp.storage as storage_cdp

from behavior import async_bezier_mouse_move, async_lognormal_type, lognormal_delay

FRONTIER_BUY = "https://frontier.com/buy"
WARMUP_URL = "https://frontier.com/why-frontier"
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = _REPO_ROOT
LOGS_DIR = os.path.join(_REPO_ROOT, "logs", "frontier")
ADDRESSES_FILE = os.path.join(
    _REPO_ROOT, "crawler", "dca_frontier", "frontier_addresses.json"
)
RESULTS_FILE = os.path.join(
    _REPO_ROOT, "crawler", "dca_frontier", "frontier_address_scopes.json"
)


def load_addresses() -> list[dict]:
    """Load addresses from frontier_addresses.json."""
    with open(ADDRESSES_FILE) as f:
        data = json.load(f)
    return data["addresses"]


def load_existing_results() -> dict[str, dict]:
    """Load previously saved scopes for reuse."""
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            data = json.load(f)
        return {r["address"]: r for r in data.get("results", [])}
    return {}


def save_reusable_results(results: list["AddressResult"]) -> None:
    """Save/merge results into frontier_address_scopes.json for reuse."""
    existing = load_existing_results()
    for r in results:
        existing[r.address] = {
            "address": r.address,
            "scope": r.scope,
            "reason": r.reason,
            "num_offers": r.num_offers,
            "offer_names": r.offer_names,
            "final_url": r.final_url,
            "last_checked": datetime.now().isoformat(),
        }
    output = {
        "last_updated": datetime.now().isoformat(),
        "total": len(existing),
        "results": list(existing.values()),
    }
    with open(RESULTS_FILE, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"  Reusable scopes saved → {RESULTS_FILE} ({len(existing)} addresses)")


@dataclass
class AddressResult:
    address: str
    scope: str
    reason: str
    num_offers: int = 0
    offer_names: list[str] = field(default_factory=list)
    final_url: str = ""
    elapsed_s: float = 0.0


async def rich_warmup(tab, duration_s: float = 20.0) -> None:
    start = time.time()
    vw = await tab.evaluate("window.innerWidth") or 1440
    vh = await tab.evaluate("window.innerHeight") or 900
    while time.time() - start < duration_s:
        action = random.choices(
            ["scroll", "move", "hover_nav", "pause", "scroll_up"],
            weights=[30, 25, 20, 15, 10],
        )[0]
        if action == "scroll":
            await tab.scroll_down(random.randint(150, 500))
            await asyncio.sleep(random.uniform(0.8, 2.0))
        elif action == "move":
            cx = await tab.evaluate("window._bhvX || window.innerWidth/2")
            cy = await tab.evaluate("window._bhvY || window.innerHeight/2")
            tx = random.uniform(80, vw - 80)
            ty = random.uniform(80, vh - 80)
            await async_bezier_mouse_move(tab, cx, cy, tx, ty, steps=18)
            await tab.evaluate(f"window._bhvX={tx}; window._bhvY={ty};")
            await asyncio.sleep(random.uniform(0.3, 1.0))
        elif action == "hover_nav":
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
    for text in ["Close", "Accept All", "Accept all"]:
        try:
            btn = await tab.find(text, timeout=2)
            if btn:
                await btn.click()
                await asyncio.sleep(0.5)
                return
        except Exception:
            continue


async def check_one_address(tab, address: str, idx: int, total: int) -> AddressResult:
    """Check a single address on the Frontier /buy page."""
    start = time.time()
    result = AddressResult(address=address, scope="UNKNOWN", reason="")
    print(f"\n  [{idx+1}/{total}] {address}")

    try:
        # Full fresh page load — cache-bust to force clean DOM + clean input
        cache_bust = f"?_cb={int(time.time())}{random.randint(100,999)}"
        await tab.get(FRONTIER_BUY + cache_bust)
        await asyncio.sleep(random.uniform(3.5, 5.0))
        await dismiss_banner(tab)
        # Scroll to top so address field is visible
        await tab.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(0.5)


        # Find address field — known selector: #street-address
        addr_field = None
        for sel in [
            "#street-address",
            "input.address-form__input",
            "input[aria-label*='address' i]",
            "input[placeholder*='address' i]",
            "[role='combobox']",
        ]:
            try:
                addr_field = await tab.query_selector(sel)
                if addr_field:
                    break
            except Exception:
                continue

        if not addr_field:
            result.scope = "INVALID_ADDRESS"
            result.reason = "Address field not found on page"
            result.elapsed_s = time.time() - start
            return result

        # Clear field using React-safe native setter, then type
        await tab.evaluate("""
            (() => {
                const input = document.querySelector('#street-address') ||
                              document.querySelector('input.address-form__input');
                if (input) {
                    input.focus();
                    const nativeSet = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    nativeSet.call(input, '');
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                }
            })()
        """)
        await asyncio.sleep(0.5)
        await addr_field.click()
        await asyncio.sleep(0.3)

        # Type the new address
        await async_lognormal_type(tab, addr_field, address)
        await asyncio.sleep(random.uniform(1.5, 3.0))

        # Select first autocomplete option
        try:
            options = await tab.query_selector_all("[role='option']")
            if options:
                await asyncio.sleep(random.uniform(0.3, 0.8))
                await options[0].click()
                print(f"         autocomplete selected")
            else:
                city_hint = address.split(",")[1].strip().split()[0] if "," in address else ""
                if city_hint:
                    try:
                        opt = await tab.find(city_hint, timeout=3)
                        if opt:
                            await opt.click()
                    except Exception:
                        pass
        except Exception:
            pass

        await asyncio.sleep(random.uniform(0.5, 1.5))

        # Click CHECK AVAILABILITY
        clicked = False
        try:
            clicked_js = await tab.evaluate("""
                (() => {
                    const btns = document.querySelectorAll('button');
                    for (const b of btns) {
                        if (b.innerText && b.innerText.toLowerCase().includes('check availability')) {
                            b.click();
                            return true;
                        }
                    }
                    return false;
                })()
            """)
            clicked = bool(clicked_js)
            if clicked:
                print(f"         clicked CHECK AVAILABILITY")
        except Exception:
            pass

        if not clicked:
            result.scope = "INVALID_ADDRESS"
            result.reason = "CHECK AVAILABILITY button not found"
            result.elapsed_s = time.time() - start
            # Navigate back for next address
            try:
                await tab.get(FRONTIER_BUY)
                await asyncio.sleep(2)
            except Exception:
                pass
            return result

        # Wait for result
        await asyncio.sleep(random.uniform(5.0, 8.0))

        # Check where we ended up
        final_url = await tab.evaluate("location.href") or ""
        result.final_url = final_url

        if "allconnect.com" in final_url:
            result.scope = "PROVIDER_NOT_AVAILABLE"
            result.reason = "Frontier not available — redirected to allconnect.com"

        elif "frontier.com" in final_url:
            page_text = await tab.evaluate("document.body.innerText") or ""
            if not isinstance(page_text, str):
                page_text = str(page_text)

            has_pricing = bool(re.search(r'\$\d+', page_text))
            has_plans = any(kw in page_text.lower() for kw in [
                "view plan", "add to cart", "shop now", "/mo", "per mo"
            ])

            if "technical difficulties" in page_text.lower():
                result.scope = "PROVIDER_NOT_AVAILABLE"
                result.reason = "Technical difficulties error (possibly commercial address)"
            elif "already a frontier customer" in page_text.lower() or "current customer" in page_text.lower():
                result.scope = "CURRENT_CUSTOMER"
                result.reason = "Page identifies existing customer"
            elif has_pricing and has_plans:
                result.scope = "PROSPECT_CUSTOMER"
                result.reason = "Plans with pricing found"
                # Quick extract plan names
                plans_raw = await tab.evaluate("""
                    JSON.stringify((() => {
                        const names = [];
                        const els = document.querySelectorAll('h2, h3, h4, [class*="plan-name" i], [class*="PlanName"]');
                        els.forEach(el => {
                            const t = el.innerText.trim();
                            if (t.match(/fiber|gig|internet/i) && t.length < 80) names.push(t);
                        });
                        return names;
                    })())
                """)
                try:
                    result.offer_names = json.loads(plans_raw) if isinstance(plans_raw, str) else []
                except Exception:
                    result.offer_names = []

                # Count offers with $ pricing
                offers_raw = await tab.evaluate("""
                    JSON.stringify((() => {
                        const cards = document.querySelectorAll('[data-testid*="plan" i], [class*="plan-card" i], [class*="PlanCard"], [class*="product-card" i]');
                        const results = [];
                        cards.forEach(c => {
                            const t = c.innerText || '';
                            if (t.includes('$')) {
                                const nameEl = c.querySelector('h2, h3, h4');
                                const priceMatch = t.match(/\\$[\\d,.]+/);
                                const speedMatch = t.match(/\\d+\\s*(?:Mbps|Gig|Gbps)/i);
                                results.push({
                                    name: nameEl ? nameEl.innerText.trim() : t.split('\\n')[0].substring(0, 60),
                                    price: priceMatch ? priceMatch[0] : '',
                                    speed: speedMatch ? speedMatch[0] : ''
                                });
                            }
                        });
                        return results;
                    })())
                """)
                try:
                    offers = json.loads(offers_raw) if isinstance(offers_raw, str) else []
                    result.num_offers = len(offers)
                    if offers and not result.offer_names:
                        result.offer_names = [o.get("name", "") for o in offers if isinstance(o, dict)]
                except Exception:
                    pass

            elif "enter your address" in page_text.lower() and not has_pricing:
                result.scope = "PROVIDER_NOT_AVAILABLE"
                result.reason = "Address entry page — plans did not load"
            elif "address not found" in page_text.lower() or "invalid" in page_text.lower():
                result.scope = "INVALID_ADDRESS"
                result.reason = "Address not recognized"
            else:
                result.scope = "PROVIDER_NOT_AVAILABLE"
                result.reason = "No pricing or plans detected on page"
        else:
            result.scope = "PROVIDER_NOT_AVAILABLE"
            result.reason = f"Unexpected redirect to {final_url[:60]}"
            await tab.get(FRONTIER_BUY)
            await asyncio.sleep(random.uniform(2.0, 3.0))

    except Exception as exc:
        result.scope = "INVALID_ADDRESS"
        result.reason = f"Error: {str(exc)[:80]}"
        try:
            await tab.get(FRONTIER_BUY)
            await asyncio.sleep(2)
        except Exception:
            pass

    result.elapsed_s = time.time() - start
    icon = {"PROSPECT_CUSTOMER": "✅", "CURRENT_CUSTOMER": "🔵",
            "PROVIDER_NOT_AVAILABLE": "❌", "INVALID_ADDRESS": "⚠️"}.get(result.scope, "❓")
    print(f"         {icon} {result.scope} ({result.elapsed_s:.1f}s) — {result.reason[:60]}")
    return result


async def run_batch(skip_cached: bool = False) -> list[AddressResult]:
    addr_list = load_addresses()
    existing = load_existing_results() if skip_cached else {}
    to_check = [a for a in addr_list if a["address"] not in existing]

    print(f"\n{'='*70}")
    print(f"  Frontier Batch Address Checker — {len(addr_list)} total addresses")
    if existing:
        print(f"  Skipping {len(existing)} already-cached addresses")
    print(f"  Checking {len(to_check)} addresses | Level 6 Stealth (nodriver)")
    print(f"{'='*70}\n")

    if not to_check:
        print("  All addresses already cached. Use --force to re-check.")
        return [AddressResult(address=a["address"], scope=existing[a["address"]]["scope"],
                              reason=existing[a["address"]]["reason"]) for a in addr_list]

    import tempfile
    tmp_dir = tempfile.mkdtemp(prefix="frontier_batch_")
    browser = await uc.start(headless=False, user_data_dir=tmp_dir)

    # Phase 1: Warm-up
    print("Phase 1: Warm-up browsing (20s)...")
    tab = await browser.get(WARMUP_URL)
    await asyncio.sleep(random.uniform(3.0, 5.0))
    await dismiss_banner(tab)
    await rich_warmup(tab, duration_s=20.0)
    print("  warm-up done\n")

    # Phase 2: Navigate to /buy
    print("Phase 2: Navigating to buy page + warm-up (15s)...")
    await tab.get(FRONTIER_BUY)
    await asyncio.sleep(random.uniform(3.0, 5.0))
    await dismiss_banner(tab)
    await rich_warmup(tab, duration_s=15.0)
    print("  ready\n")

    total = len(to_check)
    print(f"Phase 3: Checking {total} addresses...\n")
    results = []
    for i, entry in enumerate(to_check):
        addr = entry["address"]
        try:
            r = await asyncio.wait_for(
                check_one_address(tab, addr, i, total),
                timeout=45.0,
            )
        except asyncio.TimeoutError:
            r = AddressResult(
                address=addr, scope="INVALID_ADDRESS",
                reason="Hard timeout (45s) — page hung",
                elapsed_s=45.0,
            )
            print(f"         ⏱️ TIMEOUT after 45s — skipping")
            try:
                await tab.get(FRONTIER_BUY)
                await asyncio.sleep(2)
            except Exception:
                pass
        results.append(r)
        if (i + 1) % 5 == 0:
            save_reusable_results(results)
        await asyncio.sleep(random.uniform(1.0, 2.0))

    browser.stop()
    return results


def print_summary(results: list[AddressResult]) -> None:
    print(f"\n\n{'='*120}")
    print(f"  BATCH RESULTS SUMMARY — {len(results)} addresses")
    print(f"{'='*120}")
    print(f"{'#':>3} {'Scope':<26} {'Offers':>6} {'Time':>6} {'Address':<50} {'Reason':<50}")
    print(f"{'─'*3} {'─'*26} {'─'*6} {'─'*6} {'─'*50} {'─'*50}")

    for i, r in enumerate(results):
        icon = {"PROSPECT_CUSTOMER": "✅", "CURRENT_CUSTOMER": "🔵",
                "PROVIDER_NOT_AVAILABLE": "❌", "INVALID_ADDRESS": "⚠️"}.get(r.scope, "❓")
        print(f"{i+1:>3} {icon} {r.scope:<24} {r.num_offers:>6} {r.elapsed_s:>5.1f}s {r.address:<50} {r.reason[:50]}")

    # Totals
    from collections import Counter
    scope_counts = Counter(r.scope for r in results)
    print(f"\n  Totals:")
    for scope, count in scope_counts.most_common():
        print(f"    {scope}: {count}")
    total_offers = sum(r.num_offers for r in results)
    print(f"    Total offers found: {total_offers}")
    avg_time = sum(r.elapsed_s for r in results) / max(len(results), 1)
    print(f"    Average time per address: {avg_time:.1f}s")


def save_results(results: list[AddressResult]) -> str:
    os.makedirs(LOGS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(LOGS_DIR, f"batch_extraction_{ts}.json")

    data = {
        "timestamp": datetime.now().isoformat(),
        "total_addresses": len(results),
        "results": [
            {
                "address": r.address,
                "scope": r.scope,
                "reason": r.reason,
                "num_offers": r.num_offers,
                "offer_names": r.offer_names,
                "final_url": r.final_url,
                "elapsed_s": round(r.elapsed_s, 1),
            }
            for r in results
        ],
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"\n  Results saved to: {path}")
    return path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Frontier batch address checker")
    parser.add_argument("--force", action="store_true",
                        help="Re-check all addresses even if cached")
    args = parser.parse_args()

    results = uc.loop().run_until_complete(run_batch(skip_cached=not args.force))
    print_summary(results)
    save_results(results)
    save_reusable_results(results)


if __name__ == "__main__":
    main()
