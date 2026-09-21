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

## Live crawl (bot detection unchanged)

**Do not use Playwright for live Frontier checks in this repo.**

`crawler/run_addresses.py` is a thin I/O wrapper only. It calls:

`legacy/frontier_batch_stealth.check_address` (nodriver L6 — same evasion as before).

`dca_frontier/` seeds / decoder / offer_extractor and the Frontier healer exist for
**deadshot package shape** and config. They do not replace the L6 crawl path here.

```bash
# 3 addresses via legacy nodriver L6
python crawler/run_addresses.py --provider frontier --max 3

# one address
python crawler/run_addresses.py --provider frontier \
  --address "1308 Chase St, Novato, CA 94945"
```


## Legacy research

Nodriver Level 6 scripts, scorecards, and batch checkers live under `legacy/`.
See `docs/FRONTIER_PROVIDER_ONBOARDING.md` for the deadshot port checklist.
