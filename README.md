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

## Live smoke (Frontier)

```bash
python crawler/run_addresses.py --provider frontier \
  --address "1308 Chase St, Novato, CA 94945"
```

Expect `llm_calls=0` and no self-heal log lines.

## Legacy research

Nodriver Level 6 scripts, scorecards, and batch checkers live under `legacy/`.
See `docs/FRONTIER_PROVIDER_ONBOARDING.md` for the deadshot port checklist.
