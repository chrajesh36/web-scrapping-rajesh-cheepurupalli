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
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime

import nodriver as uc

_CRAWLER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "crawler")
if _CRAWLER not in sys.path:
    sys.path.insert(0, _CRAWLER)

from behavior import (
    async_bezier_mouse_move,
    async_lognormal_type,
)
from dca_bot_detection.session_score import score_session
from frontier_level6_stealth_max import get_abck_flag, rich_warmup

FRONTIER_BUY = "https://frontier.com/buy"
FRONTIER_SHOP = "https://frontier.com/shop/internet"
WARMUP_URL = "https://frontier.com/why-frontier"
# Surface I/O paths only (repo move into legacy/) — crawl logic unchanged
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = _REPO_ROOT
LOGS_DIR = os.path.join(_REPO_ROOT, "logs", "frontier")
ADDRESSES_FILE = os.path.join(
    _REPO_ROOT, "crawler", "dca_frontier", "frontier_addresses.json"
)
RESULTS_FILE = os.path.join(
    _REPO_ROOT, "crawler", "dca_frontier", "frontier_address_scopes.json"
)


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
    # Bot-detection scoring (restored — was missing from live path)
    detection_score: int = 0
    detection_verdict: str = ""
    abck_flag: str = ""
    detection_metrics: dict = field(default_factory=dict)


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


def _attach_detection_score(
    result: AddressResult,
    *,
    abck_flag: str = "",
    address_field_present: bool = True,
    soft_block_technical: bool = False,
    plans_loaded: bool = False,
    mover_seen: bool = False,
) -> AddressResult:
    """Attach bot-detection methods score to the address result."""
    sc = score_session(
        abck_flag=abck_flag,
        address_field_present=address_field_present,
        soft_block_technical=soft_block_technical
        or "technical difficulties" in (result.reason or "").lower(),
        plans_loaded=plans_loaded or result.num_offers > 0,
        mover_seen=mover_seen,
        scope_reason=result.reason,
    )
    result.detection_score = sc.detection_score
    result.detection_verdict = sc.verdict
    result.abck_flag = sc.abck_flag
    result.detection_metrics = sc.to_dict()
    print(
        f"    DETECTION_SCORE={sc.detection_score}/100  verdict={sc.verdict}  "
        f"abck={sc.abck_flag or '?'}"
    )
    for n in sc.notes:
        print(f"      • {n}")
    return result


# ── Single address check in a FRESH browser ──────────────────────────────

async def check_address(address: str, state: str, market: str,
                        proxy: str | None = None) -> AddressResult:
    """Check one address using a fresh browser session.

    Full L6 evasion stack (all directions):
      1. TLS — nodriver + system Chrome
      2. IP — optional --proxy residential
      3. Sensor — multi-page warmup + _abck patience before CHECK
      4. Behavior — rich_warmup + log-normal typing + Bezier-ready helpers
      5. Session — fresh profile per address; why-frontier → shop → buy
    """
    start = time.time()
    result = AddressResult(address=address, state=state, market=market,
                           scope="UNKNOWN", reason="")

    tmp_dir = tempfile.mkdtemp(prefix="frontier_")
    browser_args = []
    if proxy:
        browser_args.append(f"--proxy-server={proxy}")

    browser = None
    abck_flag = ""
    mover_seen = False
    try:
        browser = await uc.start(
            headless=False,
            user_data_dir=tmp_dir,
            browser_args=browser_args or None,
        )

        # Layer 5 session + Layer 3/4: multi-page warm-up (L6)
        print("    L6 Phase 1: why-frontier warmup")
        tab = await browser.get(WARMUP_URL)
        await asyncio.sleep(random.uniform(3.0, 5.0))
        await dismiss_banner(tab)
        await rich_warmup(tab, duration_s=25.0)
        print(f"    _abck after why-frontier: {await get_abck_flag(tab)}")

        print("    L6 Phase 2: shop/internet warmup")
        await tab.get(FRONTIER_SHOP)
        await asyncio.sleep(random.uniform(3.0, 5.0))
        await dismiss_banner(tab)
        await rich_warmup(tab, duration_s=25.0)
        print(f"    _abck after shop: {await get_abck_flag(tab)}")

        print("    L6 Phase 3: /buy + sensor patience")
        await tab.get(FRONTIER_BUY)
        await asyncio.sleep(random.uniform(3.0, 5.0))
        await dismiss_banner(tab)
        await tab.evaluate("window.scrollTo(0, 0)")
        for i in range(12):
            abck_flag = await get_abck_flag(tab)
            if abck_flag == "0":
                print(f"    _abck validated (0) before CHECK at wait {i+1}")
                break
            await asyncio.sleep(2)
        else:
            abck_flag = await get_abck_flag(tab)
            print(f"    _abck still {abck_flag} — proceeding carefully")

        # Address field
        field = await tab.query_selector("#street-address")
        if not field:
            field = await tab.query_selector("input.address-form__input")
        if not field:
            result.scope = "INVALID_ADDRESS"
            result.reason = "Address field not found (soft-block / bot score)"
            browser.stop()
            return _attach_detection_score(
                result,
                abck_flag=abck_flag,
                address_field_present=False,
            )

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

        await async_lognormal_type(tab, field, address)
        await asyncio.sleep(random.uniform(1.5, 3.0))

        # Autocomplete — prefer options matching address tokens
        needles = [
            t for t in re.split(r"[,\s]+", address.lower())
            if (len(t) > 2 and not t.isdigit()) or (t.isdigit() and len(t) == 5)
        ][:5]
        picked = await tab.evaluate("""
            (needles) => {
                const opts = [...document.querySelectorAll('[role="option"], li, button')];
                for (const o of opts) {
                    const t = (o.innerText || '').toLowerCase();
                    if (needles.some(n => t.includes(n)) && t.length > 5 && t.length < 200) {
                        o.click(); return t.substring(0, 120);
                    }
                }
                const first = document.querySelector('[role="option"]');
                if (first) { first.click(); return (first.innerText || '').substring(0, 120); }
                return '';
            }
        """, needles)
        print(f"    autocomplete: {picked!r}")
        await asyncio.sleep(random.uniform(0.5, 1.5))

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
            return _attach_detection_score(
                result, abck_flag=abck_flag, address_field_present=True
            )

        # Wait for plans / mover / soft errors (mover can be below fold)
        page_text = ""
        for _ in range(16):
            await asyncio.sleep(2.5)
            page_text = await tab.evaluate("document.body.innerText") or ""
            if not isinstance(page_text, str):
                page_text = str(page_text)
            page_lower = page_text.lower()
            if "are you moving to this address" in page_lower and not mover_seen:
                mover_seen = True
                await tab.evaluate("""
                    (() => {
                        for (const b of document.querySelectorAll('button, a, [role="button"]')) {
                            const t = (b.innerText || '').replace(/\\s+/g, ' ').trim().toUpperCase();
                            if (t.includes('YES') && t.includes('MOVING') && !t.includes('NOT')) {
                                b.click(); return true;
                            }
                        }
                        return false;
                    })()
                """)
                print("    mover modal → clicked YES, I'M MOVING (prospect path)")
                await asyncio.sleep(8)
                page_text = await tab.evaluate("document.body.innerText") or ""
                if not isinstance(page_text, str):
                    page_text = str(page_text)
                continue
            if any(k in page_lower for k in ("view plan", "/mo", "add to cart", "allconnect.com")):
                break
            await tab.scroll_down(200)

        abck_flag = await get_abck_flag(tab) or abck_flag
        final_url = await tab.evaluate("location.href") or ""
        result.final_url = final_url
        page_lower = (page_text or "").lower()
        soft_tech = "technical difficulties" in page_lower
        plans_loaded = False

        if "allconnect.com" in final_url:
            result.scope = "PROVIDER_NOT_AVAILABLE"
            result.reason = "Redirected to allconnect.com — Frontier not available"

        elif "frontier.com" in final_url:
            has_pricing = bool(re.search(r'\$\d+', page_text))
            has_plans = any(kw in page_lower for kw in [
                "view plan", "add to cart", "shop now", "/mo", "per mo"
            ])

            if "already a frontier customer" in page_lower or "current customer" in page_lower:
                result.scope = "CURRENT_CUSTOMER"
                result.reason = "Existing customer detected"
            elif has_pricing and has_plans:
                result.scope = "PROSPECT_CUSTOMER"
                result.reason = "Plans with pricing found"
                plans_loaded = True
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
            elif mover_seen or "are you moving" in page_lower:
                result.scope = "PROSPECT_CUSTOMER"
                result.reason = "Serviceable — mover question shown (prospect path)"
            elif "isn't available" in page_lower or "not available at your address" in page_lower:
                result.scope = "PROVIDER_NOT_AVAILABLE"
                result.reason = "Frontier not available at this address"
            elif soft_tech:
                result.scope = "PROVIDER_NOT_AVAILABLE"
                result.reason = (
                    "Technical difficulties soft-block "
                    "(often IP reputation / order API — try residential proxy)"
                )
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
        _attach_detection_score(
            result,
            abck_flag=abck_flag,
            address_field_present=True,
            soft_block_technical=soft_tech,
            plans_loaded=plans_loaded,
            mover_seen=mover_seen,
        )

    except Exception as exc:
        result.scope = "INVALID_ADDRESS"
        result.reason = f"Error: {str(exc)[:80]}"
        try:
            if browser:
                browser.stop()
        except Exception:
            pass
        _attach_detection_score(
            result,
            abck_flag=abck_flag,
            address_field_present=False,
        )

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
                timeout=240.0,
            )
        except asyncio.TimeoutError:
            r = AddressResult(address=addr, state=state, market=market,
                              scope="INVALID_ADDRESS",
                              reason="Hard timeout (240s)", elapsed_s=240.0)
            _attach_detection_score(r, address_field_present=False)

        icon = {"PROSPECT_CUSTOMER": "✅", "CURRENT_CUSTOMER": "🔵",
                "PROVIDER_NOT_AVAILABLE": "❌", "INVALID_ADDRESS": "⚠️"}.get(r.scope, "❓")
        print(
            f"         {icon} {r.scope} det={r.detection_score}/100 "
            f"({r.elapsed_s:.0f}s) — {r.reason[:55]}"
        )

        results.append(r)
        merged[addr] = {
            "address": addr, "state": state, "market": market,
            "scope": r.scope, "reason": r.reason,
            "num_offers": r.num_offers, "offer_names": r.offer_names,
            "final_url": r.final_url, "last_checked": datetime.now().isoformat(),
            "detection_score": r.detection_score,
            "detection_verdict": r.detection_verdict,
            "abck_flag": r.abck_flag,
            "detection_metrics": r.detection_metrics,
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
    print(f"\n\n{'='*130}")
    print(f"  RESULTS — {len(results)} addresses (with bot-detection scores)")
    print(f"{'='*130}")
    print(f"{'#':>3} {'St':>3} {'Scope':<24} {'Det':>5} {'Time':>5} {'Address':<45} {'Reason'}")
    print(f"{'─'*3} {'─'*3} {'─'*24} {'─'*5} {'─'*5} {'─'*45} {'─'*40}")

    for i, r in enumerate(results):
        icon = {"PROSPECT_CUSTOMER": "✅", "CURRENT_CUSTOMER": "🔵",
                "PROVIDER_NOT_AVAILABLE": "❌", "INVALID_ADDRESS": "⚠️"}.get(r.scope, "❓")
        print(
            f"{i+1:>3} {r.state:>3} {icon} {r.scope:<22} {r.detection_score:>3}/100 "
            f"{r.elapsed_s:>4.0f}s {r.address:<45} {r.reason[:40]}"
        )

    from collections import Counter
    counts = Counter(r.scope for r in results)
    print(f"\n  Totals:")
    for scope, count in counts.most_common():
        print(f"    {scope}: {count}")
    if results:
        avg = sum(r.detection_score for r in results) / len(results)
        print(f"  Avg detection score: {avg:.0f}/100 (0=human, 100=blocked)")


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
                timeout=240.0,
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
                "detection_score": r.detection_score,
                "detection_verdict": r.detection_verdict,
                "abck_flag": r.abck_flag,
                "detection_metrics": r.detection_metrics,
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
        json.dump({
            "results": [
                {
                    "address": r.address,
                    "state": r.state,
                    "scope": r.scope,
                    "reason": r.reason,
                    "elapsed_s": r.elapsed_s,
                    "detection_score": r.detection_score,
                    "detection_verdict": r.detection_verdict,
                    "abck_flag": r.abck_flag,
                }
                for r in results
            ]
        }, f, indent=2)
    print(f"\n  Log → {log_path}")
    print(f"  Scopes → {RESULTS_FILE}")


if __name__ == "__main__":
    main()
