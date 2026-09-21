"""Live smoke runner — packaging I/O only.

Bot evasion / crawl logic is unchanged: delegates to legacy nodriver L6
(``legacy/frontier_batch_stealth.check_address``).

Usage:
    python crawler/run_addresses.py --provider frontier --address "1308 Chase St, Novato, CA 94945"
    python crawler/run_addresses.py --provider frontier --max 3
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime

_CRAWLER_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_CRAWLER_DIR)
_LEGACY_DIR = os.path.join(_REPO_ROOT, "legacy")

# Surface-level path wiring so legacy imports (behavior, etc.) resolve
if _LEGACY_DIR not in sys.path:
    sys.path.insert(0, _LEGACY_DIR)
if _CRAWLER_DIR not in sys.path:
    sys.path.insert(0, _CRAWLER_DIR)

from frontier_batch_stealth import (  # noqa: E402  — legacy L6 crawl, unmodified
    check_address,
    load_addresses,
)

# Output naming for deadshot packaging (INVALID_ADDRESS → UNKNOWN_ADDRESS)
_SCOPE_OUT = {
    "INVALID_ADDRESS": "UNKNOWN_ADDRESS",
}


def _map_scope(scope: str) -> str:
    return _SCOPE_OUT.get(scope, scope)


async def run_one(address: str, state: str = "", market: str = "",
                  proxy: str | None = None) -> dict:
    print(f"provider=frontier engine=legacy_nodriver_l6 llm_calls=0")
    print(f"crawl=legacy/frontier_batch_stealth.check_address (bot-detection unchanged)")
    r = await asyncio.wait_for(
        check_address(address, state or "??", market or "smoke", proxy),
        timeout=180.0,
    )
    scope = _map_scope(r.scope)
    out = {
        "provider": "frontier",
        "address": r.address,
        "state": r.state,
        "market": r.market,
        "scope": scope,
        "scope_reason": r.reason,
        "num_offers": r.num_offers,
        "offer_names": r.offer_names,
        "final_url": r.final_url,
        "elapsed_s": r.elapsed_s,
        "llm_calls": 0,
        "outcome": "completed" if scope != "UNKNOWN_ADDRESS" or r.num_offers else (
            "ERROR_PROCESSING" if "not found" in (r.reason or "").lower()
            or "field" in (r.reason or "").lower()
            else "completed"
        ),
        "healer": "dca_recipe_engine.steps.healers.frontier",
        "crawl_backend": "legacy/frontier_batch_stealth.py",
    }
    print(f"outcome={out['outcome']} llm_calls=0 scope={scope}")
    print(json.dumps(out, indent=2)[:1500])
    return out


async def run_many(max_n: int = 3, proxy: str | None = None) -> list[dict]:
    addrs = load_addresses()[:max_n]
    # Prefer Chase first if present in scopes file intent — always include known prospect
    preferred = "1308 Chase St, Novato, CA 94945"
    rows = [{"address": preferred, "state": "CA", "market": "Novato"}]
    for a in addrs:
        if a["address"] != preferred:
            rows.append(a)
        if len(rows) >= max_n:
            break

    results = []
    for i, row in enumerate(rows):
        print("\n" + "=" * 72)
        print(f"[{i+1}/{len(rows)}] {row['address']}")
        print("=" * 72)
        try:
            results.append(
                await run_one(row["address"], row.get("state", ""), row.get("market", ""), proxy)
            )
        except Exception as exc:
            results.append({
                "provider": "frontier",
                "address": row["address"],
                "scope": "ERROR",
                "scope_reason": str(exc),
                "offers": [],
                "llm_calls": 0,
                "outcome": "ERROR_PROCESSING",
                "crawl_backend": "legacy/frontier_batch_stealth.py",
            })
            print(f"FAILED: {exc}")
        if i < len(rows) - 1:
            wait = 60
            print(f"Cooldown cooldown {wait}s...")
            await asyncio.sleep(wait)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Frontier smoke test — legacy L6 nodriver crawl (structure/IO wrapper only)"
    )
    parser.add_argument("--provider", default="frontier")
    parser.add_argument("--address", default=None)
    parser.add_argument("--max", type=int, default=3, help="How many addresses when --address omitted")
    parser.add_argument("--proxy", default=os.environ.get("FRONTIER_PROXY"))
    args = parser.parse_args()
    if args.provider.lower() != "frontier":
        raise SystemExit(f"Only frontier is wired (got {args.provider})")

    out_dir = os.path.join(_REPO_ROOT, "logs", "frontier")
    os.makedirs(out_dir, exist_ok=True)

    if args.address:
        results = uc_run(run_one(args.address, proxy=args.proxy))
        results = [results]
    else:
        results = uc_run(run_many(max_n=args.max, proxy=args.proxy))

    path = os.path.join(
        out_dir, f"restructure_smoke_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(path, "w") as f:
        json.dump({"checked": datetime.now().isoformat(), "results": results}, f, indent=2)

    print("\n=== SUMMARY ===")
    for r in results:
        print(
            f"  {r.get('scope', '?'):<24} offers={r.get('num_offers', len(r.get('offer_names') or []))} "
            f"outcome={r.get('outcome')} llm={r.get('llm_calls')}"
        )
        print(f"    {r.get('address')}")
        print(f"    {str(r.get('scope_reason', ''))[:120]}")
    print(f"Saved {path}")


def uc_run(coro):
    import nodriver as uc
    return uc.loop().run_until_complete(coro)


if __name__ == "__main__":
    main()
