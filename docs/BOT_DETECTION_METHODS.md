# Bot detection methods & scoring

Restored as first-class package after the folder restructure: these modules
were under `legacy/` and no longer surfaced on the live crawl path.

## Package: `crawler/dca_bot_detection/`

| Module | Role |
|--------|------|
| `api_logger.py` | Network capture, sensor POSTs, `_abck` before/after, Excel |
| `bot_scorecard.py` | Full 0–100 scorecard from ApiLogger / Excel logs |
| `behavior.py` | Bezier mouse, log-normal typing, warmup |
| `methods.py` | Catalog of Akamai/vendor detection methods we counter |
| `session_score.py` | Live per-address detection score during L6 crawl |

Legacy shims (`legacy/api_logger.py`, `behavior.py`, `bot_scorecard.py`) re-export
the package so older scripts keep working.

## Detection methods (what they look for)

1. **TLS/JA4** — Playwright Chromium fingerprint ≠ Chrome UA  
2. **IP reputation** — datacenter ASN / high qualify velocity  
3. **Sensor + `_abck`** — flag `-1` = failed, `0` = validated human  
4. **Behavior** — mouse/keyboard/scroll unnatural  
5. **Session** — smash `/buy` without multi-page cookie lifecycle  
6. **App soft-block** — “technical difficulties”, missing `#street-address`, empty plans  

Counters: nodriver L6 + multi-page warmup + `_abck` patience + `--proxy` + fresh profile.

## Scoring

### Live session (`SessionDetectionScore`) — every address check

| Signal | Points |
|--------|--------|
| `_abck` not validated | +40 |
| `_abck` missing | +10 |
| No address field | +30 |
| Technical-difficulties text | +20 |
| Plans empty after submit | +15 |

Bands: ≤20 LOW · ≤45 MODERATE · ≤70 HIGH · ≤100 CRITICAL  
Printed as `DETECTION_SCORE=N/100` and stored on each result JSON.

### Full Excel scorecard (`BotScorecard`)

```bash
cd legacy
PYTHONPATH=.:../crawler python bot_scorecard.py
```

Uses historical `logs/*.xlsx` captures (403s, sensor POSTs, cookie timeline).

## Wired entry points

- `legacy/frontier_batch_stealth.check_address` → attaches score  
- `crawler/run_addresses.py` → includes `detection_score` in output  
- `docs/BOT_EVASION.md` → evasion layers  

## Import

```python
from dca_bot_detection import BotScorecard, ApiLogger, score_session
from dca_bot_detection.methods import DETECTION_METHODS
```
