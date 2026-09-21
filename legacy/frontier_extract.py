"""Frontier broadband plan extractor — Level 6 stealth.

Extracts:
  1. scope: CURRENT_CUSTOMER | PROSPECT_CUSTOMER | INVALID_ADDRESS | PROVIDER_NOT_AVAILABLE
  2. offers: list of plan descriptions with broadband facts

Uses nodriver (Level 6 Stealth Max approach) for bot evasion,
with CDP Network.getResponseBody to capture API response data.

Usage:
    python frontier_extract.py --address "2727 LBJ Freeway, Dallas, TX 75234"
    python frontier_extract.py --address "123 Fake Street, Nowhere, XX 00000"
"""

from __future__ import annotations

import argparse
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

from behavior import (
    async_bezier_mouse_move,
    async_lognormal_type,
    lognormal_delay,
)

FRONTIER_URL = "https://frontier.com/shop/internet"
WARMUP_URL = "https://frontier.com/why-frontier"
LOGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "frontier")


# ── Data models ──────────────────────────────────────────────────────────

@dataclass
class PlanOffer:
    name: str
    price: str
    speed: str
    description: str
    features: list[str] = field(default_factory=list)
    broadband_facts: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "price": self.price,
            "speed": self.speed,
            "description": self.description,
            "features": self.features,
            "broadband_facts": self.broadband_facts,
        }


@dataclass
class ExtractionResult:
    address: str
    scope: str
    scope_reason: str
    offers: list[PlanOffer] = field(default_factory=list)
    raw_api_responses: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "address": self.address,
            "scope": self.scope,
            "scope_reason": self.scope_reason,
            "offers": [o.to_dict() for o in self.offers],
        }


# ── CDP response body capture ───────────────────────────────────────────

class ApiCapture:
    """Captures specific API response bodies via CDP."""

    def __init__(self):
        self._pending: dict[str, dict] = {}
        self.captured: dict[str, dict] = {}
        self._tab = None

        self.WATCH_PATTERNS = [
            "serviceability",
            "order/create",
            "data-live.json",
            "predictive",
        ]

    async def enable(self, tab) -> None:
        self._tab = tab
        tab.add_handler(net.RequestWillBeSent, self._on_request)
        tab.add_handler(net.ResponseReceived, self._on_response)
        await tab.send(net.enable())

    def _on_request(self, event: net.RequestWillBeSent) -> None:
        req = event.request
        url = req.url or ""
        if any(p in url.lower() for p in self.WATCH_PATTERNS):
            payload = ""
            if req.has_post_data and req.post_data:
                payload = req.post_data
            self._pending[str(event.request_id)] = {
                "url": url,
                "method": req.method,
                "payload": payload,
            }

    def _on_response(self, event: net.ResponseReceived) -> None:
        req_id = str(event.request_id)
        if req_id in self._pending:
            pending = self._pending[req_id]
            pending["status"] = event.response.status
            pending["request_id"] = event.request_id
            asyncio.get_event_loop().create_task(self._fetch_body(event.request_id, pending))

    async def _fetch_body(self, request_id, info: dict) -> None:
        """Fetch response body via CDP Network.getResponseBody."""
        await asyncio.sleep(0.3)
        try:
            result = await self._tab.send(net.get_response_body(request_id))
            body_text = result[0] if result else ""
            info["body"] = body_text
            url = info["url"]
            key = url.split("?")[0].split("/")[-1] or url
            self.captured[key] = info
            print(f"    [API] Captured: {info['method']} {info['status']} {url[:80]}  ({len(body_text)} chars)")
        except Exception as exc:
            info["body"] = ""
            info["error"] = str(exc)


# ── Behavioral helpers ───────────────────────────────────────────────────

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
                        await tab.evaluate(f"window._bhvX={pos.x}; window._bhvY={pos.y};")
                        await asyncio.sleep(random.uniform(0.4, 1.2))
            except Exception:
                await asyncio.sleep(0.5)
        elif action == "scroll_up":
            await tab.scroll_up(random.randint(100, 300))
            await asyncio.sleep(random.uniform(0.5, 1.5))
        else:
            await asyncio.sleep(random.uniform(1.0, 2.5))


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


# ── Scope determination ──────────────────────────────────────────────────

def determine_scope(api_capture: ApiCapture, page_text: str) -> tuple[str, str]:
    """Determine scope from captured API data and page content."""

    page_lower = page_text.lower()

    # Check API responses for serviceability
    for key, info in api_capture.captured.items():
        body = info.get("body", "")
        if not body:
            continue
        body_lower = body.lower()

        # Parse JSON if possible
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            data = None

        if "serviceability" in key.lower() or "predictive" in key.lower():
            if data:
                # Look for common serviceability flags
                status = data.get("status", "")
                serviceable = data.get("serviceable", data.get("isServiceable", None))
                in_footprint = data.get("inFootPrint", data.get("inFootprint", None))
                existing = data.get("existingCustomer", data.get("isExistingCustomer", None))

                if existing is True or str(status).upper() == "EXISTING_CUSTOMER":
                    return "CURRENT_CUSTOMER", f"API returned existingCustomer=True (status={status})"
                if serviceable is False or str(status).upper() in ("NOT_SERVICEABLE", "OUT_OF_FOOTPRINT"):
                    return "PROVIDER_NOT_AVAILABLE", f"API returned serviceable=False (status={status})"
                if in_footprint is False:
                    return "PROVIDER_NOT_AVAILABLE", f"API returned inFootPrint=False"
                if serviceable is True or in_footprint is True:
                    return "PROSPECT_CUSTOMER", f"API returned serviceable=True (status={status})"

            if "not serviceable" in body_lower or "out of footprint" in body_lower:
                return "PROVIDER_NOT_AVAILABLE", "API body contains 'not serviceable'"
            if "existing customer" in body_lower or "current customer" in body_lower:
                return "CURRENT_CUSTOMER", "API body mentions existing/current customer"

    # Fallback: check page DOM content
    if "already a frontier customer" in page_lower or "current customer" in page_lower:
        return "CURRENT_CUSTOMER", "Page text mentions existing customer"
    if "we couldn" in page_lower and "find" in page_lower:
        return "INVALID_ADDRESS", "Page says address could not be found"
    if "not available" in page_lower and "address" in page_lower:
        return "PROVIDER_NOT_AVAILABLE", "Page says service not available at address"
    if "address not found" in page_lower or "invalid address" in page_lower:
        return "INVALID_ADDRESS", "Page says address not found/invalid"
    if "no plans available" in page_lower or "no service" in page_lower:
        return "PROVIDER_NOT_AVAILABLE", "Page says no plans available"

    # Check if actual plan offers with pricing are present on page
    has_pricing = bool(re.search(r'\$\d+', page_text))
    has_plan_action = any(kw in page_lower for kw in [
        "add to cart", "view plan", "shop now", "per mo", "/mo",
    ])
    if has_pricing and has_plan_action:
        return "PROSPECT_CUSTOMER", "Page shows plan offers (pricing + action buttons detected in DOM)"
    if has_pricing and any(kw in page_lower for kw in ["fiber", "gig", "mbps", "internet plan"]):
        return "PROSPECT_CUSTOMER", "Page shows plan offers (pricing + plan names detected in DOM)"

    # Soft blocks / errors
    if "technical difficulties" in page_lower:
        return "PROVIDER_NOT_AVAILABLE", "Page shows 'technical difficulties' error (address may be commercial or blocked)"
    if "isn't available at your address" in page_lower or "not available at your address" in page_lower:
        return "PROVIDER_NOT_AVAILABLE", "Frontier is not available at this address"

    # Address entry page without plans
    if "enter your address" in page_lower and not has_pricing:
        return "PROVIDER_NOT_AVAILABLE", "Page shows address entry but no plans loaded"

    return "PROVIDER_NOT_AVAILABLE", "No offers or serviceability signals detected"


# ── Plan extraction from DOM ─────────────────────────────────────────────

async def extract_plans_from_dom(tab) -> list[PlanOffer]:
    """Scrape plan cards from the rendered Frontier page."""
    plans = []

    # Dump page structure for debugging — use JSON.stringify for nodriver compat
    debug_raw = await tab.evaluate("""
    JSON.stringify((() => {
        const body = document.body.innerText || '';
        const allEls = document.querySelectorAll('*');
        const planEls = [];
        for (const el of allEls) {
            const cls = el.className || '';
            const tid = el.getAttribute('data-testid') || '';
            const tag = el.tagName;
            const txt = (el.innerText || '').substring(0, 100);
            if ((typeof cls === 'string') && (
                cls.match(/plan|product|offer|card|pricing/i) ||
                tid.match(/plan|product|offer|card/i)
            )) {
                planEls.push({
                    tag: tag,
                    cls: typeof cls === 'string' ? cls.substring(0, 120) : '',
                    testid: tid,
                    text: txt,
                    childCount: el.children.length
                });
            }
        }
        return {
            url: location.href,
            bodyLength: body.length,
            planElements: planEls.slice(0, 30),
            bodyPreview: body.substring(0, 3000)
        };
    })())
    """)

    debug_info = None
    try:
        debug_info = json.loads(debug_raw) if isinstance(debug_raw, str) else debug_raw
    except Exception:
        pass

    if debug_info and isinstance(debug_info, dict):
        print(f"    Page URL: {debug_info.get('url', '')[:80]}")
        print(f"    Body length: {debug_info.get('bodyLength', 0)} chars")
        plan_els = debug_info.get("planElements", [])
        if plan_els:
            print(f"    Found {len(plan_els)} plan-related elements:")
            for pe in plan_els[:10]:
                if isinstance(pe, dict):
                    print(f"      <{pe.get('tag','')} class=\"{str(pe.get('cls',''))[:60]}\" testid=\"{pe.get('testid','')}\" children={pe.get('childCount',0)}>")
                    txt = pe.get('text', '')
                    if txt:
                        print(f"        text: {txt[:80]}")
        body_preview = debug_info.get("bodyPreview", "")
        if body_preview:
            print(f"    Body preview (first 500 chars):")
            for line in body_preview[:500].split("\n")[:8]:
                if line.strip():
                    print(f"      {line.strip()[:100]}")

    js_extract = """
    JSON.stringify((() => {
        const results = [];

        // Strategy 1: Look for plan/product cards with broad selectors
        const cardSelectors = [
            '[data-testid*="plan"]', '[data-testid*="Plan"]',
            '[data-testid*="product"]', '[data-testid*="Product"]',
            '[data-testid*="offer"]', '[data-testid*="Offer"]',
            '[class*="plan-card"]', '[class*="PlanCard"]', '[class*="planCard"]',
            '[class*="product-card"]', '[class*="ProductCard"]', '[class*="productCard"]',
            '[class*="offer-card"]', '[class*="OfferCard"]', '[class*="offerCard"]',
            'article[class*="plan"]', 'section[class*="plan"]',
            '[class*="InternetPlan"]', '[class*="internet-plan"]',
            '[class*="PricingCard"]', '[class*="pricing-card"]',
        ];
        let cards = [];
        for (const sel of cardSelectors) {
            try {
                const found = document.querySelectorAll(sel);
                if (found.length > 0 && found.length <= 10) {
                    cards = Array.from(found);
                    break;
                }
            } catch(e) {}
        }

        if (cards.length > 0) {
            cards.forEach(card => {
                const text = card.innerText || '';
                if (text.length < 20) return;
                const nameEl = card.querySelector('h1, h2, h3, h4, [class*="name" i], [class*="title" i], [class*="Name"], [class*="Title"]');
                const priceEl = card.querySelector('[class*="price" i], [class*="Price"], [class*="amount" i], [class*="Amount"]');
                const speedEl = card.querySelector('[class*="speed" i], [class*="Speed"], [class*="Mbps"], [class*="Gig"]');
                const priceMatch = text.match(/\\$[\\d,.]+/);
                const speedMatch = text.match(/\\d+\\s*(?:Mbps|Gig|Gbps)/i);
                results.push({
                    name: nameEl ? nameEl.innerText.trim() : (text.split('\\n')[0] || '').substring(0, 80),
                    price: priceEl ? priceEl.innerText.trim() : (priceMatch ? priceMatch[0] : ''),
                    speed: speedEl ? speedEl.innerText.trim() : (speedMatch ? speedMatch[0] : ''),
                    full_text: text.substring(0, 3000),
                    source: 'card_selector'
                });
            });
        }

        // Strategy 2: Split body text by plan-like boundaries
        if (results.length === 0) {
            const body = document.body.innerText || '';
            // Look for repeated patterns like "Fiber 500", "Fiber 1 Gig", etc.
            const planPattern = /(?:Fiber\\s+\\d+|Fiber\\s+\\d+\\s*Gig|Internet\\s+\\d+)/gi;
            const matches = [...body.matchAll(planPattern)];
            if (matches.length > 0) {
                for (let i = 0; i < matches.length; i++) {
                    const start = matches[i].index;
                    const end = (i + 1 < matches.length) ? matches[i+1].index : start + 1500;
                    const chunk = body.substring(start, Math.min(end, start + 3000));
                    const priceMatch = chunk.match(/\\$[\\d,.]+/);
                    const speedMatch = chunk.match(/\\d+\\s*(?:Mbps|Gig|Gbps)/i);
                    results.push({
                        name: matches[i][0],
                        price: priceMatch ? priceMatch[0] : '',
                        speed: speedMatch ? speedMatch[0] : '',
                        full_text: chunk,
                        source: 'body_split'
                    });
                }
            }
        }

        // Strategy 3: Find any div/section that contains $ pricing
        if (results.length === 0) {
            const candidates = document.querySelectorAll('section, [class*="plans" i], [class*="Plans"], main');
            for (const sec of candidates) {
                const text = sec.innerText || '';
                if (text.match(/\\$\\d+/) && text.match(/fiber|gig|mbps|internet|speed/i) && text.length > 100) {
                    const priceBlocks = text.split(/(?=\\$\\d)/);
                    for (const block of priceBlocks) {
                        if (block.match(/\\$\\d/) && block.length > 30) {
                            const priceMatch = block.match(/\\$[\\d,.]+/);
                            const speedMatch = block.match(/\\d+\\s*(?:Mbps|Gig|Gbps)/i);
                            const nameMatch = block.match(/Fiber\\s+[\\w\\d\\s]+|Internet\\s+[\\w\\d]+/i);
                            results.push({
                                name: nameMatch ? nameMatch[0].trim() : '',
                                price: priceMatch ? priceMatch[0] : '',
                                speed: speedMatch ? speedMatch[0] : '',
                                full_text: block.substring(0, 2000),
                                source: 'price_split'
                            });
                        }
                    }
                    if (results.length > 0) break;
                }
            }
        }

        // Strategy 4: Broadest fallback — full page text
        if (results.length === 0) {
            const body = document.body.innerText || '';
            results.push({
                name: 'Full Page Content',
                price: '',
                speed: '',
                full_text: body.substring(0, 5000),
                source: 'body_fallback'
            });
        }

        return results;
    })())
    """

    try:
        raw_result = await tab.evaluate(js_extract)
        raw_plans = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
        if raw_plans and isinstance(raw_plans, list):
            for rp in raw_plans:
                if not isinstance(rp, dict):
                    continue
                name = rp.get("name", "") or "Unnamed Plan"
                full_text = rp.get("full_text", "")

                features = []
                for line in full_text.split("\n"):
                    line = line.strip()
                    if line and len(line) > 10 and len(line) < 200:
                        if any(kw in line.lower() for kw in [
                            "included", "free", "unlimited", "no contract",
                            "wi-fi", "wifi", "router", "speed", "upload",
                            "download", "data", "equipment", "installation",
                        ]):
                            features.append(line)

                plan = PlanOffer(
                    name=name,
                    price=rp.get("price", ""),
                    speed=rp.get("speed", ""),
                    description=full_text[:2000],
                    features=features[:10],
                    broadband_facts="",
                )
                plans.append(plan)
        elif raw_plans:
            print(f"    Unexpected JS return type: {type(raw_plans).__name__}")
    except Exception as exc:
        print(f"  DOM extraction error: {exc}")

    return plans


async def extract_broadband_facts(tab, plans: list[PlanOffer]) -> None:
    """Try to find and extract broadband facts / nutrition labels."""
    # First try: look for broadband facts links anywhere on the page
    try:
        facts_links = await tab.find_all("Broadband Facts")
    except Exception:
        facts_links = []

    if not facts_links:
        try:
            facts_links = await tab.find_all("broadband facts")
        except Exception:
            facts_links = []

    if not facts_links:
        try:
            facts_links = await tab.find_all("Broadband Label")
        except Exception:
            facts_links = []

    print(f"    Found {len(facts_links)} broadband facts link(s)")

    for i, link in enumerate(facts_links):
        if i >= len(plans):
            break
        try:
            await link.scroll_into_view()
            await asyncio.sleep(random.uniform(0.5, 1.0))
            await link.click()
            await asyncio.sleep(random.uniform(2.0, 4.0))

            facts_text = await tab.evaluate("""
                (() => {
                    // Check for modals/dialogs first
                    const modals = document.querySelectorAll(
                        '[role="dialog"], [class*="modal" i], [class*="Modal"], ' +
                        '[class*="overlay" i], [class*="Overlay"], [class*="drawer" i]'
                    );
                    for (const m of modals) {
                        const t = m.innerText || '';
                        if (t.length > 100 && (t.includes('Broadband') || t.includes('broadband') ||
                            t.includes('Monthly') || t.includes('Typical'))) {
                            return t;
                        }
                    }
                    // Check for inline broadband facts sections
                    const all = document.querySelectorAll('div, section, table');
                    for (const el of all) {
                        const t = el.innerText || '';
                        if ((t.includes('Broadband Facts') || t.includes('broadband facts')) &&
                            t.length > 100 && t.length < 8000) {
                            return t;
                        }
                    }
                    return '';
                })()
            """)

            if facts_text:
                plans[i].broadband_facts = facts_text[:4000]
                print(f"    ✓ Broadband facts for plan {i+1}: {plans[i].name[:40]} ({len(facts_text)} chars)")

            # Close modal/overlay
            try:
                close_btn = await tab.find("Close", timeout=2)
                if close_btn:
                    await close_btn.click()
            except Exception:
                pass
            try:
                await tab.send(uc.cdp.input_.dispatch_key_event(
                    type_="keyDown", key="Escape", code="Escape",
                    windows_virtual_key_code=27, native_virtual_key_code=27,
                ))
            except Exception:
                pass
            await asyncio.sleep(0.5)

        except Exception as exc:
            print(f"    Could not get broadband facts for plan {i+1}: {exc}")

    # If no individual links found, try extracting any broadband facts text already on page
    if not facts_links:
        all_facts = await tab.evaluate("""
            (() => {
                const body = document.body.innerText || '';
                const idx = body.indexOf('Broadband Facts');
                if (idx >= 0) return body.substring(idx, idx + 3000);
                const idx2 = body.indexOf('broadband facts');
                if (idx2 >= 0) return body.substring(idx2, idx2 + 3000);
                return '';
            })()
        """)
        if all_facts and plans:
            plans[0].broadband_facts = all_facts[:4000]
            print(f"    Found inline broadband facts text ({len(all_facts)} chars)")


# ── Main extraction flow ─────────────────────────────────────────────────

async def extract(address: str, proxy: str | None = None) -> ExtractionResult:
    print(f"\n{'='*64}")
    print(f"  Frontier Plan Extractor (Level 6 Stealth)")
    print(f"  Address: {address}")
    print(f"{'='*64}\n")

    browser_args = []
    if proxy:
        browser_args.append(f"--proxy-server={proxy}")

    browser = await uc.start(
        headless=False,
        browser_args=browser_args or None,
    )

    api_capture = ApiCapture()
    result = ExtractionResult(address=address, scope="UNKNOWN", scope_reason="")

    try:
        # Phase 1: Warm-up on non-protected page
        print("Phase 1: Warm-up page...")
        tab = await browser.get(WARMUP_URL)
        await api_capture.enable(tab)
        await asyncio.sleep(random.uniform(3.0, 5.0))
        await dismiss_cookie_banner(tab)
        await rich_warmup(tab, duration_s=20.0)
        print("    warm-up done")

        # Phase 2: Navigate to target and warm-up
        print("\nPhase 2: Target page + warm-up...")
        await tab.get(FRONTIER_URL)
        await asyncio.sleep(random.uniform(3.0, 5.0))
        await dismiss_cookie_banner(tab)
        await rich_warmup(tab, duration_s=20.0)
        print("    target warm-up done")

        # Phase 3: Enter address
        print(f"\nPhase 3: Entering address: {address}")
        address_field = None
        for sel in [
            "input[aria-label*='Street Address']",
            "input[placeholder*='Enter your address']",
            "input[aria-label*='address']",
        ]:
            try:
                address_field = await tab.query_selector(sel)
                if address_field:
                    break
            except Exception:
                continue
        if not address_field:
            try:
                address_field = await tab.find("Enter your address", timeout=10)
            except Exception:
                pass

        if not address_field:
            result.scope = "INVALID_ADDRESS"
            result.scope_reason = "Could not find address input field (page likely blocked)"
            return result

        await address_field.click()
        await address_field.clear_input()
        await async_lognormal_type(tab, address_field, address)
        await asyncio.sleep(random.uniform(2.0, 4.0))

        # Try autocomplete
        city_hint = address.split(",")[1].strip().split()[0] if "," in address else ""
        try:
            if city_hint:
                suggestion = await tab.find(city_hint, timeout=5)
            else:
                suggestion = await tab.query_selector("[role='option']")
            if suggestion:
                await asyncio.sleep(random.uniform(0.5, 1.5))
                await suggestion.click()
                print("    selected autocomplete suggestion")
        except Exception:
            print("    no autocomplete — continuing")

        await asyncio.sleep(random.uniform(0.5, 1.5))

        # Click check availability
        try:
            check_btn = await tab.find("Check availability", timeout=8)
            if check_btn:
                await check_btn.click()
                print("    clicked 'Check availability'")
        except Exception:
            print("    no Check availability button found")

        # Wait for redirect or plan loading
        print("\n    Waiting for results...")
        await asyncio.sleep(random.uniform(5.0, 8.0))

        # Check current URL via JS (tab.target.url can be stale after redirects)
        current_url = await tab.evaluate("location.href") or ""
        print(f"    Current URL: {current_url[:80]}")
        if "/buy" in current_url:
            print(f"    Redirected to: {current_url[:80]}")

            # Check if plans are already shown or address entry needed
            page_check = await tab.evaluate(
                "document.body.innerText.includes('$') && "
                "document.body.innerText.match(/fiber|gig|mbps/i) ? 'has_plans' : 'needs_address'"
            )
            
            if page_check != "has_plans":
                print("    Buy page needs address re-entry...")
                buy_addr = None
                for sel in [
                    "input[aria-label*='address' i]",
                    "input[placeholder*='Enter your address' i]",
                    "input[placeholder*='address' i]",
                    "[role='combobox']",
                ]:
                    try:
                        buy_addr = await tab.query_selector(sel)
                        if buy_addr:
                            break
                    except Exception:
                        continue
                if not buy_addr:
                    try:
                        buy_addr = await tab.find("Enter your address", timeout=5)
                    except Exception:
                        pass

                if buy_addr:
                    await buy_addr.click()
                    await buy_addr.clear_input()
                    await async_lognormal_type(tab, buy_addr, address)
                    await asyncio.sleep(random.uniform(2.0, 4.0))

                    # Select the FIRST autocomplete option (exact address or first suite)
                    option_selected = False
                    try:
                        options = await tab.query_selector_all("[role='option']")
                        if options:
                            await asyncio.sleep(random.uniform(0.5, 1.0))
                            await options[0].click()
                            option_selected = True
                            print(f"    selected first autocomplete option on buy page")
                    except Exception:
                        pass
                    if not option_selected:
                        try:
                            if city_hint:
                                option = await tab.find(city_hint, timeout=3)
                            else:
                                option = await tab.find(address.split(",")[0].split()[-1], timeout=3)
                            if option:
                                await option.click()
                                option_selected = True
                                print("    selected autocomplete by text on buy page")
                        except Exception:
                            pass

                    await asyncio.sleep(random.uniform(1.0, 2.0))

                    # Close the dropdown if still open by clicking elsewhere first
                    if not option_selected:
                        try:
                            header = await tab.query_selector("h1, header")
                            if header:
                                await header.click()
                                await asyncio.sleep(0.5)
                        except Exception:
                            pass

                    # Click CHECK AVAILABILITY
                    for btn_text in ["CHECK AVAILABILITY", "Check availability", "Check Availability"]:
                        try:
                            cb = await tab.find(btn_text, timeout=3)
                            if cb:
                                await cb.click()
                                print(f"    clicked '{btn_text}' on buy page")
                                break
                        except Exception:
                            continue

                    # Wait for plans to load — retry with scroll
                    print("    Waiting for plans to load...")
                    for attempt in range(5):
                        await asyncio.sleep(random.uniform(3.0, 5.0))
                        has_plans = await tab.evaluate(
                            "document.body.innerText.includes('$') && "
                            "document.body.innerText.match(/\\/mo|per mo|View plan|Add to cart/i) "
                            "? true : false"
                        )
                        if has_plans:
                            print(f"    Plans detected after {attempt+1} wait(s)")
                            break
                        await tab.scroll_down(400)
                        await asyncio.sleep(1)
                    else:
                        print("    Plans may not have loaded — extracting what's available")
                else:
                    print("    Could not find address field on buy page")

        # Final wait: scroll and wait for any late-rendering content
        await asyncio.sleep(2)
        for _ in range(3):
            await tab.scroll_down(350)
            await asyncio.sleep(random.uniform(1.0, 2.0))
        await tab.scroll_up(800)
        await asyncio.sleep(2)

        # Phase 4: Extract data
        print("\nPhase 4: Extracting data...")

        # Get current URL and full page text
        final_url = await tab.evaluate("location.href") or ""
        print(f"    Final URL: {final_url[:100]}")

        # If redirected to allconnect.com → Frontier not available
        if "allconnect.com" in final_url:
            result.scope = "PROVIDER_NOT_AVAILABLE"
            result.scope_reason = "Redirected to allconnect.com — Frontier not available at this address"
            print(f"    Scope: {result.scope}")
            print(f"    Reason: {result.scope_reason}")
            browser.stop()
            return result

        page_text = await tab.evaluate("document.body.innerText") or ""
        if not isinstance(page_text, str):
            page_text = str(page_text)

        # Dump page text for debugging
        print(f"    Page text length: {len(page_text)} chars")
        preview_lines = [l.strip() for l in page_text[:1500].split("\n") if l.strip()]
        print(f"    Page content preview:")
        for line in preview_lines[:15]:
            print(f"      {line[:100]}")

        # Determine scope
        result.scope, result.scope_reason = determine_scope(api_capture, page_text)
        print(f"    Scope: {result.scope}")
        print(f"    Reason: {result.scope_reason}")

        # Always attempt plan extraction (plans might be below fold)
        print("\n    Extracting plan details from DOM...")
        try:
            plans = await extract_plans_from_dom(tab)
            if plans:
                real_plans = [p for p in plans if p.price or "$" in p.description]
                if real_plans:
                    print(f"    Found {len(real_plans)} plan(s) with pricing")
                    await extract_broadband_facts(tab, real_plans)
                    result.offers = real_plans
                    if result.scope != "CURRENT_CUSTOMER":
                        result.scope = "PROSPECT_CUSTOMER"
                        result.scope_reason = f"Found {len(real_plans)} plan(s) with pricing in DOM"
                else:
                    print(f"    Found {len(plans)} element(s) but none with pricing")
            else:
                print("    No plans extracted from DOM")
        except Exception as exc:
            print(f"    Plan extraction error: {exc}")

        # Store raw API data
        for key, info in api_capture.captured.items():
            result.raw_api_responses[key] = {
                "url": info.get("url", ""),
                "method": info.get("method", ""),
                "status": info.get("status", ""),
                "body_length": len(info.get("body", "")),
            }

    except Exception as exc:
        print(f"\nERROR: {exc}")
        if result.scope == "UNKNOWN":
            result.scope = "INVALID_ADDRESS"
            result.scope_reason = f"Extraction failed: {exc}"
    finally:
        browser.stop()

    return result


def save_result(result: ExtractionResult) -> str:
    """Save extraction result to JSON."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(LOGS_DIR, f"extraction_{ts}.json")

    output = result.to_dict()
    output["raw_api_responses"] = result.raw_api_responses

    with open(path, "w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\nResult saved to: {path}")
    return path


def print_result(result: ExtractionResult) -> None:
    print(f"\n{'='*64}")
    print(f"  EXTRACTION RESULT")
    print(f"{'='*64}")
    print(f"  Address: {result.address}")
    print(f"  Scope:   {result.scope}")
    print(f"  Reason:  {result.scope_reason}")
    print(f"  Offers:  {len(result.offers)}")

    for i, offer in enumerate(result.offers):
        print(f"\n  ── Offer {i+1} ──")
        print(f"  Name:  {offer.name[:80]}")
        print(f"  Price: {offer.price}")
        print(f"  Speed: {offer.speed}")
        if offer.description:
            desc_lines = offer.description[:300].split("\n")
            for line in desc_lines[:5]:
                if line.strip():
                    print(f"    {line.strip()}")
        if offer.broadband_facts:
            print(f"  Broadband Facts: ({len(offer.broadband_facts)} chars captured)")
            facts_lines = offer.broadband_facts[:200].split("\n")
            for line in facts_lines[:3]:
                if line.strip():
                    print(f"    {line.strip()}")

    print(f"\n{'='*64}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Frontier broadband plan extractor")
    parser.add_argument("--address", type=str,
                        default="2727 LBJ Freeway, Dallas, TX 75234",
                        help="Service address to check")
    parser.add_argument("--proxy", type=str, default=None,
                        help="Proxy URL, e.g. http://user:pass@host:port")
    args = parser.parse_args()

    result = uc.loop().run_until_complete(extract(args.address, proxy=args.proxy))
    print_result(result)
    save_result(result)


if __name__ == "__main__":
    main()
