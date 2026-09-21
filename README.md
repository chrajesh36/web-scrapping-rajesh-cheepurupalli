# Verizon Broadband Plans Automation

A small Python + Playwright script that opens Verizon's home internet plans
page, enters a service address, then clicks through each broadband plan card
in the results before closing the browser.

## Prerequisites

- Python 3.9+
- macOS/Linux/Windows

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Run

```bash
python verizon_plans.py
```

A Chromium window will open, load `https://www.verizon.com/home/internet/`,
enter the hardcoded address, then click each plan card in turn. Progress
messages are printed to the console.

## Configuring the address

Edit the `ADDRESS` dict at the top of `verizon_plans.py`:

```python
ADDRESS = {
    "street": "140 West Street",
    "unit": "",
    "city": "New York",
    "state": "NY",
    "zip": "10007",
}
```

## Notes on selectors

Verizon updates their site frequently. The script tries multiple selector
strategies for each step (address input, submit button, plan cards, CTAs),
so it should survive small changes. If a step fails, run with the browser
visible (the default) and inspect the DOM in DevTools, then add a matching
selector to the appropriate `*_candidates` list in `verizon_plans.py`.

## Tuning waits

All timeouts and pauses are centralized in the `Timing` dataclass near the
top of the script. Increase `page_load` or `element` on slower networks.
