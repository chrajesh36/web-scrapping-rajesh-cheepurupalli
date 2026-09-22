# Bot evasion — all directions (Frontier live crawl)

Live Frontier checks in **this repo** always go through **nodriver L6**.
Playwright modules under `crawler/dca_frontier/` are packaging for deadshot only
and are **not** used for live crawl here.

## Entry points (all L6)

| Entry | Backend |
|-------|---------|
| `crawler/run_addresses.py` | `legacy/frontier_batch_stealth.check_address` |
| `legacy/frontier_batch_stealth.py` | nodriver L6 (primary) |
| `legacy/frontier_chase_recheck.py` | nodriver L6 + mover debug |
| `legacy/frontier_extract.py` | nodriver L6 extractor |
| `legacy/frontier_level6_stealth_max.py` | full L6 reference run |

## Five Akamai layers covered

1. **TLS / protocol** — nodriver raw CDP + system Chrome (no Playwright handshake)
2. **IP reputation** — `--proxy` / `FRONTIER_PROXY` on all runners; fresh browser per address
3. **Sensor / cookies** — multi-page warmup; wait for `_abck` flag `0` before CHECK when possible
4. **Behavior** — `dca_bot_detection.behavior` Bezier mouse, log-normal typing, `rich_warmup`
5. **Session** — `/why-frontier` → `/shop/internet` → `/buy`; temp profile per address; cooldown between checks

Methods catalog + live/Excel scoring: `docs/BOT_DETECTION_METHODS.md` and
`crawler/dca_bot_detection/`.

## Soft-block vs hard ban

- **Hard ban:** 403 / blank / no cookies / no address field
- **Soft IP block (current home IP):** form works, offers API returns technical-difficulties / empty plans → use residential proxy

## Do not

- Do not point live smoke at Playwright `async_playwright` for Frontier
- Do not reuse one browser cookie jar across many addresses
- Do not fire CHECK while `_abck` is still `-1` if you can wait
