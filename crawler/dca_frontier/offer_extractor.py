"""Frontier DOM offer extraction — Playwright port of legacy frontier_extract.py."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from playwright.async_api import Page


@dataclass
class PlanOffer:
    name: str
    price: str
    speed: str
    description: str
    features: list[str] = field(default_factory=list)
    broadband_facts: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "price": self.price,
            "speed": self.speed,
            "description": self.description,
            "features": self.features,
            "broadband_facts": self.broadband_facts,
        }


JS_EXTRACT = """
() => {
    const results = [];
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
        } catch (e) {}
    }

    if (cards.length > 0) {
        cards.forEach(card => {
            const text = card.innerText || '';
            if (text.length < 20) return;
            const nameEl = card.querySelector(
                'h1, h2, h3, h4, [class*="name" i], [class*="title" i], [class*="Name"], [class*="Title"]'
            );
            const priceEl = card.querySelector(
                '[class*="price" i], [class*="Price"], [class*="amount" i], [class*="Amount"]'
            );
            const speedEl = card.querySelector(
                '[class*="speed" i], [class*="Speed"], [class*="Mbps"], [class*="Gig"]'
            );
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

    if (results.length === 0) {
        const body = document.body.innerText || '';
        const planPattern = /(?:Fiber\\s+\\d+|Fiber\\s+\\d+\\s*Gig|Internet\\s+\\d+)/gi;
        const matches = [...body.matchAll(planPattern)];
        for (let i = 0; i < matches.length; i++) {
            const start = matches[i].index;
            const end = (i + 1 < matches.length) ? matches[i + 1].index : start + 1500;
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
}
"""


def _features_from_text(full_text: str) -> list[str]:
    features: list[str] = []
    for line in full_text.split("\n"):
        line = line.strip()
        if line and 10 < len(line) < 200:
            if any(
                kw in line.lower()
                for kw in (
                    "included",
                    "free",
                    "unlimited",
                    "no contract",
                    "wi-fi",
                    "wifi",
                    "router",
                    "speed",
                    "upload",
                    "download",
                    "data",
                    "equipment",
                    "installation",
                )
            ):
                features.append(line)
    return features[:10]


async def extract_plans_from_dom(page: Page) -> list[PlanOffer]:
    """Scrape plan cards from the rendered Frontier page (Playwright)."""
    plans: list[PlanOffer] = []
    try:
        raw = await page.evaluate(JS_EXTRACT)
    except Exception as exc:
        print(f"  DOM extraction error: {exc}")
        return plans

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return plans

    if not isinstance(raw, list):
        return plans

    for rp in raw:
        if not isinstance(rp, dict):
            continue
        full_text = rp.get("full_text", "") or ""
        plans.append(
            PlanOffer(
                name=(rp.get("name") or "Unnamed Plan"),
                price=rp.get("price", "") or "",
                speed=rp.get("speed", "") or "",
                description=full_text[:2000],
                features=_features_from_text(full_text),
            )
        )
    return plans


async def extract_broadband_facts(page: Page, plans: list[PlanOffer]) -> None:
    """Attach broadband-facts / nutrition-label text when present."""
    if not plans:
        return

    links = page.get_by_text(re.compile(r"broadband facts|broadband label", re.I))
    count = await links.count()
    print(f"    Found {count} broadband facts link(s)")

    for i in range(min(count, len(plans))):
        try:
            link = links.nth(i)
            await link.scroll_into_view_if_needed()
            await link.click(timeout=5000)
            await page.wait_for_timeout(2000)
            facts_text = await page.evaluate(
                """() => {
                    const modals = document.querySelectorAll(
                        '[role="dialog"], [class*="modal" i], [class*="Modal"]'
                    );
                    for (const m of modals) {
                        const t = m.innerText || '';
                        if (t.length > 100 && /broadband|monthly|typical/i.test(t)) return t;
                    }
                    const body = document.body.innerText || '';
                    const idx = body.search(/broadband facts/i);
                    return idx >= 0 ? body.substring(idx, idx + 3000) : '';
                }"""
            )
            if facts_text:
                plans[i].broadband_facts = str(facts_text)[:4000]
            await page.keyboard.press("Escape")
        except Exception as exc:
            print(f"    Could not get broadband facts for plan {i + 1}: {exc}")

    if count == 0:
        inline = await page.evaluate(
            """() => {
                const body = document.body.innerText || '';
                const idx = body.search(/broadband facts/i);
                return idx >= 0 ? body.substring(idx, idx + 3000) : '';
            }"""
        )
        if inline:
            plans[0].broadband_facts = str(inline)[:4000]


def determine_scope_from_page(page_text: str, url: str = "") -> tuple[str, str]:
    """Map page text → scope. Uses UNKNOWN_ADDRESS (deadshot naming)."""
    page_lower = (page_text or "").lower()
    url_l = (url or "").lower()

    if "already a frontier customer" in page_lower or "current customer" in page_lower:
        return "CURRENT_CUSTOMER", "Page text mentions existing customer"
    if "are you moving to this address" in page_lower:
        return "PROSPECT_CUSTOMER", "Mover question — address is serviceable"
    if "allconnect.com" in url_l:
        return "PROVIDER_NOT_AVAILABLE", "Redirected to allconnect.com"
    if "we couldn" in page_lower and "find" in page_lower:
        return "UNKNOWN_ADDRESS", "Page says address could not be found"
    if "address not found" in page_lower or "invalid address" in page_lower:
        return "UNKNOWN_ADDRESS", "Page says address not found/invalid"
    if "not available" in page_lower and "address" in page_lower:
        return "PROVIDER_NOT_AVAILABLE", "Service not available at address"
    if "isn't available at your address" in page_lower:
        return "PROVIDER_NOT_AVAILABLE", "Frontier not available at this address"

    has_pricing = bool(re.search(r"\$\d+", page_text or ""))
    has_plan_action = any(
        kw in page_lower for kw in ("add to cart", "view plan", "shop now", "per mo", "/mo")
    )
    if has_pricing and has_plan_action:
        return "PROSPECT_CUSTOMER", "Plans with pricing on page"
    if has_pricing and any(kw in page_lower for kw in ("fiber", "gig", "mbps", "internet plan")):
        return "PROSPECT_CUSTOMER", "Plan pricing + names on page"

    if "technical difficulties" in page_lower:
        return (
            "PROVIDER_NOT_AVAILABLE",
            "Technical difficulties soft error (may be IP rate-limit / order API fail)",
        )
    if "enter your address" in page_lower and not has_pricing:
        return "PROVIDER_NOT_AVAILABLE", "Address entry page — plans did not load"
    return "PROVIDER_NOT_AVAILABLE", "No offers or serviceability signals detected"
