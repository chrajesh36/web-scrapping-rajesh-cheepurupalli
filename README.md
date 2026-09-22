# Web scraping — Rajesh Cheepurupalli

Frontier (and Verizon research) broadband plan extraction with **bot-detection
methods + scoring** restored as a first-class package, packaged for drop-in to
deadshot-plugins-ai as a Tier-1 deterministic provider.

## Repo layout

| Path | Purpose |
|------|---------|
| `crawler/dca_bot_detection/` | **ApiLogger, BotScorecard, behavior, methods, session_score** |
| `crawler/dca_frontier/` | Recipe seeds / decoder / offer extractor + L6 crawl wrapper |
| `crawler/dca_recipe_engine/` | Schema stubs + deterministic Frontier healer |
| `crawler/run_addresses.py` | Live smoke → L6 + detection_score in JSON |
| `docs/BOT_DETECTION_METHODS.md` | Methods catalog + scoring rubric |
| `docs/BOT_EVASION.md` | Five-layer evasion map |
| `docs/FRONTIER_PROVIDER_ONBOARDING.md` | Deadshot onboarding |
| `legacy/` | L3–L6 runners (import bot-detection via shims) |
| `logs/`, `reports/` | Captures / Word reports |

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ./crawler
pip install -r requirements.txt
pip install pytest
python -m playwright install chromium
```

## Bot detection scoring (live)

Every address check prints and stores:

```text
DETECTION_SCORE=55/100  verdict=HIGH — ...
```

```bash
python crawler/run_addresses.py --provider frontier --max 3
# Full Excel scorecards from past captures:
PYTHONPATH=legacy:crawler python legacy/bot_scorecard.py
```

See `docs/BOT_DETECTION_METHODS.md`.

## Live crawl (L6 nodriver — not Playwright)

```bash
python crawler/run_addresses.py --provider frontier --max 3
python crawler/run_addresses.py --provider frontier \
  --address "1308 Chase St, Novato, CA 94945" \
  --proxy "http://user:pass@host:port"
```

## Tests

```bash
pytest tracer/test -q
```
