# FRONTIER_PROVIDER_ONBOARDING.md

Port Frontier from the research scripts in `legacy/` into this repo as a
**deterministic-only (Tier-1)** provider: fixed recipe, **zero LLM / vision
self-heal**, Playwright page API (not nodriver).

Target layout matches `apm0015603-deadshot-plugins-ai`.

## 1. Package layout

```
crawler/
  pyproject.toml                 # include = ["dca_*"]
  run_addresses.py               # live smoke test
  ai_agents_config/
    ai_agents_config.json        # provider=frontier, engine=recipe
  dca_frontier/
    __init__.py
    seeds.py                     # ProviderRecipe navigation
    decoder.py                   # plain JSON serviceability parse
    offer_extractor.py           # DOM plans + broadband facts
  dca_recipe_engine/
    schema.py / seeds.py / pipeline_context.py
    steps/healers/
      __init__.py                # get_healer(provider) dynamic import
      generic.py
      frontier.py                # deterministic-only healer
docs/
  FRONTIER_PROVIDER_ONBOARDING.md
legacy/                          # original nodriver / L3–L6 research scripts
tracer/test/
  test_frontier_package.py
```

## 2. Config (`ai_agents_config.json`)

- `provider`: `"frontier"`
- `engine`: `"recipe"` (required)
- `diagnose_enabled`: `false`
- `step_defaults.vision_agent_enabled`: `false`
- Scope naming: use **`UNKNOWN_ADDRESS`** (not `INVALID_ADDRESS` from legacy)

## 3. Deterministic-only healer

`crawler/dca_recipe_engine/steps/healers/frontier.py` must never call an LLM
or write `recipe_history` / Mongo. On step failure return immediately with
`detection_method="deterministic"` and an `ERROR_PROCESSING`-style message.

`get_healer("frontier")` loads this module; other providers fall back to
`generic.py`.

## 4. Verification checklist

1. Install the crawler package:

   ```bash
   pip install -e ./crawler
   ```

   Confirm `dca_frontier` is included via `include = ["dca_*"]` in
   `crawler/pyproject.toml`.

2. Run unit tests (Optimum / other providers must not change):

   ```bash
   pytest tracer/test
   ```

3. Live smoke test (known Frontier address):

   ```bash
   python crawler/run_addresses.py --provider frontier \
     --address "1308 Chase St, Novato, CA 94945"
   ```

   Expect in logs:

   - `outcome=completed` (or explicit Tier-1 `ERROR_PROCESSING` on broken selectors)
   - `llm_calls=0`
   - **no** heal signals: `step0.healed|step1_address.heal_pending|step2a.healed|step2b.signal_added|step3a.healed`
   - no `recipe_history` rows for `provider="frontier"` in `open_ai_agents_config`

4. Broken selector should return `ERROR_PROCESSING` immediately — not self-heal.

## 5. Drop-in to deadshot-plugins-ai

Copy these paths into `apm0015603-deadshot-plugins-ai`:

- `crawler/dca_frontier/`
- `crawler/dca_recipe_engine/steps/healers/frontier.py`
- Frontier block from `crawler/ai_agents_config/ai_agents_config.json`

Replace local `dca_recipe_engine` stubs with the real engine package already
in that repo (keep only the Frontier healer override).
