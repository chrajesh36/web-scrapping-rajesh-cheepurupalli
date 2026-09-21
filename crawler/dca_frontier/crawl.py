"""Live Frontier crawl entry for the dca_frontier package.

Delegates to legacy nodriver L6 — does not use Playwright for browsing.
"""

from __future__ import annotations

import asyncio
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_LEGACY = os.path.join(_REPO, "legacy")
if _LEGACY not in sys.path:
    sys.path.insert(0, _LEGACY)

from frontier_batch_stealth import check_address  # noqa: E402


async def crawl_address(
    address: str,
    state: str = "",
    market: str = "",
    proxy: str | None = None,
):
    """Run one address with full L6 bot-evasion stack."""
    return await check_address(address, state or "??", market or "dca_frontier", proxy)


def crawl_address_sync(address: str, proxy: str | None = None):
    import nodriver as uc

    return uc.loop().run_until_complete(crawl_address(address, proxy=proxy))
