# Web scraping — Rajesh Cheepurupalli

Frontier (and Verizon research) broadband plan extraction, packaged for
drop-in to **deadshot-plugins-ai** as a Tier-1 deterministic provider.

## Repo layout

| Path | Purpose |
|------|---------|
| `crawler/dca_frontier/` | Playwright recipe: seeds, decoder, offer extractor |
| `crawler/dca_recipe_engine/` | Schema stubs + **deterministic-only** Frontier healer |
| `crawler/ai_agents_config/` | Provider config (`engine: recipe`, no vision/LLM) |
| `crawler/run_addresses.py` | Live smoke test |
| `tracer/test/` | Package unit tests |
| `docs/FRONTIER_PROVIDER_ONBOARDING.md` | Onboarding checklist |
| `legacy/` | Original nodriver / L3–L6 bot-evasion research scripts |
| `logs/`, `reports/` | Capture artifacts |

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ./crawler
pip install pytest
python -m playwright install chromium
```

## Tests

```bash
pytest tracer/test -q
```

## Live crawl (bot detection unchanged — all 5 layers)

**Do not use Playwright for live Frontier checks in this repo.**

`crawler/run_addresses.py` and `dca_frontier.crawl` call:

`legacy/frontier_batch_stealth.check_address` (nodriver L6).

See `docs/BOT_EVASION.md` for the five-layer stack and entry-point map.

```bash
# 3 addresses via legacy nodriver L6
python crawler/run_addresses.py --provider frontier --max 3

# one address (+ optional residential proxy)
python crawler/run_addresses.py --provider frontier \
  --address "1308 Chase St, Novato, CA 94945" \
  --proxy "http://user:pass@host:port"
```


## Legacy research

Nodriver Level 6 scripts, scorecards, and batch checkers live under `legacy/`.
See `docs/FRONTIER_PROVIDER_ONBOARDING.md` for the deadshot port checklist.
