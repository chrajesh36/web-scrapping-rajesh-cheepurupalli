"""Catalog of bot-detection methods we observe and counter on Frontier/Verizon."""

from __future__ import annotations

# Each entry: what the vendor checks → how we counter → how we score it.
DETECTION_METHODS = [
    {
        "id": "tls_ja4",
        "layer": 1,
        "vendor": "Akamai Bot Manager",
        "method": "TLS/JA4 fingerprint vs User-Agent (Playwright Chromium mismatch)",
        "signals": ["JA4 hash", "HTTP/2 SETTINGS", "CDP handshake artifacts"],
        "our_counter": "nodriver raw CDP + system Chrome (L5/L6)",
        "score_weight": 25,
        "metric_keys": ["tls_stack"],
    },
    {
        "id": "ip_reputation",
        "layer": 2,
        "vendor": "Akamai / CDN",
        "method": "ASN type (datacenter vs residential), velocity of /buy qualifies",
        "signals": ["soft technical-difficulties", "empty plan API", "403 bursts"],
        "our_counter": "residential --proxy, fresh browser per address, cooldown",
        "score_weight": 25,
        "metric_keys": ["soft_block_technical", "plans_loaded"],
    },
    {
        "id": "sensor_abck",
        "layer": 3,
        "vendor": "Akamai Bot Manager",
        "method": "JS sensor POSTs + _abck cookie flag (-1 failed / 0 validated)",
        "signals": ["_abck~-1~", "_abck~0~", "bm_sz", "ak_bmsc", "sensor 201"],
        "our_counter": "multi-page warmup, rich_warmup, wait for _abck=0 before CHECK",
        "score_weight": 40,
        "metric_keys": ["abck_flag", "abck_validated"],
    },
    {
        "id": "behavioral",
        "layer": 4,
        "vendor": "Akamai / Quantum Metric",
        "method": "Mouse trajectories, keystroke timing, scroll velocity, hover patterns",
        "signals": ["sensor payload fields", "quantummetric ingest"],
        "our_counter": "behavior.py Bezier mouse, log-normal typing, natural scroll",
        "score_weight": 15,
        "metric_keys": ["warmup_done"],
    },
    {
        "id": "session_cookie",
        "layer": 5,
        "vendor": "Akamai",
        "method": "Cookie lifecycle + multi-page browsing before protected action",
        "signals": ["single-page smash-and-grab", "shared _abck across many checks"],
        "our_counter": "why-frontier → shop → buy; temp profile per address",
        "score_weight": 15,
        "metric_keys": ["multipage_warmup", "fresh_profile"],
    },
    {
        "id": "dom_soft_block",
        "layer": 0,
        "vendor": "Frontier app",
        "method": "UI soft-blocks when order/qualify API fails bot score",
        "signals": [
            "technical difficulties",
            "no #street-address",
            "plans did not load",
            "855-266-2406",
        ],
        "our_counter": "detect + score; do not treat as out-of-footprint",
        "score_weight": 20,
        "metric_keys": ["address_field_present", "soft_block_technical", "plans_loaded"],
    },
]


SCORING_RUBRIC = {
    "description": (
        "detection_score 0–100 where 0 = looks human / offers reachable, "
        "100 = fully blocked. Higher = worse for automation."
    ),
    "bands": [
        {"max": 20, "verdict": "LOW — session largely trusted"},
        {"max": 45, "verdict": "MODERATE — partial soft-block (e.g. API empty)"},
        {"max": 70, "verdict": "HIGH — form issues or _abck stuck at -1"},
        {"max": 100, "verdict": "CRITICAL — hard/soft ban (no field / 403)"},
    ],
    "live_session_points": {
        "abck_not_validated": 40,
        "abck_missing": 10,
        "no_address_field": 30,
        "soft_block_technical": 20,
        "no_plans_after_submit": 15,
        "http_hint_blocked": 15,
    },
}


def methods_summary_table() -> list[tuple[str, str, str]]:
    """Rows: layer method, counter, weight — for docs/README."""
    return [
        (f"L{m['layer']} {m['method'][:50]}", m["our_counter"][:50], str(m["score_weight"]))
        for m in DETECTION_METHODS
    ]
