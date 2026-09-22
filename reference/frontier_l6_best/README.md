# Frontier L6 best (reference)

Self-contained copy of the **best bot-evasion run** (Sep 9, 2026):

| Metric | Value |
|--------|------:|
| Detection score | **5 / 100** (lower = better) |
| Verdict | LIKELY UNDETECTED |
| `_abck` | `0` (validated) |
| HTTP 403 | 0 |
| Sensor POSTs | 14 |
| Residual penalty | +5 CAPTCHA scripts only |

Golden capture: `logs/GOLDEN_score_5_of_100_20260909.xlsx`

This folder is independent of the rest of the repo — copy it to another laptop and run.

## What’s inside

| File | Role |
|------|------|
| `frontier_level6_stealth_max.py` | **Best crawl** — nodriver L6 + multi-page warmup + sensor patience |
| `behavior.py` | Bezier mouse, log-normal typing, scroll |
| `api_logger.py` | Network / cookie / sensor capture → Excel |
| `bot_scorecard.py` | Detection score 0–100 |
| `score_run.py` | Re-score any Excel log vs golden |
| `requirements.txt` | Python deps |
| `logs/` | Golden baseline + new run outputs |

## Laptop setup

```bash
# 1. Copy this whole folder somewhere, e.g.:
#    ~/frontier_l6_best/

cd ~/frontier_l6_best   # or wherever you copied it

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Need a real Chrome/Chromium installed (nodriver uses it, not Playwright)
```

## Run (aim for ≤5/100)

```bash
# Default Dallas address from the golden run
python frontier_level6_stealth_max.py

# Your address
python frontier_level6_stealth_max.py --address "1308 Chase St, Novato, CA 94945"

# Recommended if datacenter / burned IP soft-blocks offers
python frontier_level6_stealth_max.py --proxy "http://user:pass@host:port" \
  --address "1308 Chase St, Novato, CA 94945"
```

After the browser closes, the script prints **THIS RUN: N/100** and writes:

- `logs/frontier_level6_stealth_max_<timestamp>.xlsx`
- `logs/frontier_level6_stealth_max_<timestamp>_scorecard.xlsx`

Re-score anytime:

```bash
python score_run.py
python score_run.py logs/GOLDEN_score_5_of_100_20260909.xlsx
```

## What “best” means

Score **≤5** needs:

1. `_abck` flips to **0** (sensor / TLS / behavior OK)
2. No soft-block (“technical difficulties”)
3. Plans page loads (often needs **residential proxy** if IP is burned)

A trusted session on a bad IP can still get ~15–70 even with this same code.

## Not included

Repo packaging (`crawler/`, healers, batch multi-address). Those wrap this same L6 logic; this folder is the **reference crawl that scored 5**.
