"""Live smoke test runner for Frontier (deterministic recipe).

Usage:
    python -m run_addresses --provider frontier --address "1308 Chase St, Novato, CA 94945"
    python crawler/run_addresses.py --provider frontier --address "..."
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

# Allow running from repo root without install
_CRAWLER_DIR = os.path.dirname(os.path.abspath(__file__))
if _CRAWLER_DIR not in sys.path:
    sys.path.insert(0, _CRAWLER_DIR)

from playwright.async_api import async_playwright

from dca_frontier.offer_extractor import (
    determine_scope_from_page,
    extract_broadband_facts,
    extract_plans_from_dom,
)
from dca_frontier.seeds import BUY_URL, START_URL, frontier_seed_recipe
from dca_recipe_engine.steps.healers import get_healer


async def run_frontier(address: str, headed: bool = True) -> dict:
    recipe = frontier_seed_recipe()
    healer = get_healer("frontier")
    assert healer.__class__.__module__.endswith("frontier")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not headed)
        context = await browser.new_context()
        page = await context.new_page()

        print(f"provider=frontier engine=recipe llm_calls=0")
        print(f"recipe_steps={[s.name for s in recipe.steps]}")
        print(f"start_url={START_URL}")

        await page.goto(START_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(2000)
        for label in ("Accept All", "Close"):
            try:
                await page.get_by_role("button", name=label).first.click(timeout=2000)
            except Exception:
                pass

        await page.goto(BUY_URL, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(3000)

        field = page.locator("#street-address")
        if await field.count() == 0:
            print("outcome=ERROR_PROCESSING reason=no_address_field")
            await browser.close()
            return {
                "provider": "frontier",
                "address": address,
                "scope": "UNKNOWN_ADDRESS",
                "scope_reason": "No address field",
                "offers": [],
                "llm_calls": 0,
                "outcome": "ERROR_PROCESSING",
            }

        await field.click()
        await page.evaluate(
            """() => {
                const input = document.querySelector('#street-address');
                if (!input) return;
                const s = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                s.call(input, '');
                input.dispatchEvent(new Event('input', {bubbles: true}));
            }"""
        )
        await field.type(address, delay=80)
        await page.wait_for_timeout(2500)

        # Autocomplete
        await page.evaluate(
            """(needles) => {
                const opts = [...document.querySelectorAll('[role="option"], li, button')];
                for (const o of opts) {
                    const t = (o.innerText || '').toLowerCase();
                    if (needles.some(n => t.includes(n)) && t.length > 5 && t.length < 200) {
                        o.click(); return t;
                    }
                }
                const first = document.querySelector('[role="option"]');
                if (first) { first.click(); return first.innerText || ''; }
                return '';
            }""",
            [t for t in address.lower().replace(",", " ").split() if len(t) > 2][:4],
        )
        await page.wait_for_timeout(1000)

        clicked = await page.evaluate(
            """() => {
                for (const b of document.querySelectorAll('button')) {
                    if ((b.innerText || '').toLowerCase().includes('check availability')) {
                        b.click(); return true;
                    }
                }
                return false;
            }"""
        )
        print(f"check_availability={clicked}")

        for _ in range(20):
            await page.wait_for_timeout(2500)
            body = await page.inner_text("body")
            body_l = body.lower()
            if "are you moving to this address" in body_l:
                await page.evaluate(
                    """() => {
                        for (const b of document.querySelectorAll('button')) {
                            const t = (b.innerText || '').toUpperCase();
                            if (t.includes('YES') && t.includes('MOVING') && !t.includes('NOT')) {
                                b.click(); return true;
                            }
                        }
                        return false;
                    }"""
                )
                await page.wait_for_timeout(6000)
                break
            if any(k in body_l for k in ("view plan", "/mo", "add to cart", "allconnect.com")):
                break

        body = await page.inner_text("body")
        url = page.url
        scope, reason = determine_scope_from_page(body, url)
        plans = await extract_plans_from_dom(page)
        priced = [p for p in plans if p.price or "$" in p.description]
        if priced:
            await extract_broadband_facts(page, priced)
            if scope not in ("CURRENT_CUSTOMER",):
                scope = "PROSPECT_CUSTOMER"
                reason = f"Found {len(priced)} plan(s) with pricing"

        outcome = "completed"
        if scope in ("UNKNOWN_ADDRESS",) and not priced:
            outcome = "ERROR_PROCESSING"

        result = {
            "provider": "frontier",
            "address": address,
            "scope": scope,
            "scope_reason": reason,
            "offers": [p.to_dict() for p in priced],
            "final_url": url,
            "llm_calls": 0,
            "outcome": outcome,
            "healer": "dca_recipe_engine.steps.healers.frontier",
        }
        print(f"outcome={outcome} llm_calls=0 scope={scope}")
        print(json.dumps(result, indent=2)[:2000])
        await browser.close()
        return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Frontier smoke test (deterministic)")
    parser.add_argument("--provider", default="frontier")
    parser.add_argument(
        "--address",
        default="1308 Chase St, Novato, CA 94945",
        help="Service address to check",
    )
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    if args.provider.lower() != "frontier":
        raise SystemExit(f"Only frontier is implemented in this repo (got {args.provider})")
    asyncio.run(run_frontier(args.address, headed=not args.headless))


if __name__ == "__main__":
    main()
