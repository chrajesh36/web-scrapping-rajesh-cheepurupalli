"""Frontier API body parsers — plain JSON (no flat-encoded Optimum-style payloads)."""

from __future__ import annotations

import json
from typing import Any


def decode_serviceability(body: str) -> dict[str, Any]:
    """Parse a serviceability / predictive API response into a flat dict."""
    if not body or not str(body).strip():
        return {}

    try:
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return {"raw": str(body)[:2000], "parse_error": True}

    if not isinstance(data, dict):
        return {"raw": data}

    flat: dict[str, Any] = {}
    for key in (
        "status",
        "serviceable",
        "isServiceable",
        "inFootPrint",
        "inFootprint",
        "existingCustomer",
        "isExistingCustomer",
        "message",
        "error",
        "errorCode",
        "addressKey",
        "qualificationId",
    ):
        if key in data:
            flat[key] = data[key]

    # Nested common shapes
    for nest in ("data", "result", "qualification", "serviceability"):
        node = data.get(nest)
        if isinstance(node, dict):
            for k, v in node.items():
                flat.setdefault(k, v)

    flat["serviceable"] = flat.get(
        "serviceable", flat.get("isServiceable")
    )
    flat["in_footprint"] = flat.get(
        "inFootPrint", flat.get("inFootprint")
    )
    flat["existing_customer"] = flat.get(
        "existingCustomer", flat.get("isExistingCustomer")
    )
    return flat


def decode_scope_from_bodies(bodies: dict[str, str]) -> tuple[str, str]:
    """Map captured API bodies → scope using deadshot naming (UNKNOWN_ADDRESS)."""
    for key, body in (bodies or {}).items():
        key_l = (key or "").lower()
        if "serviceability" not in key_l and "predictive" not in key_l:
            continue
        flat = decode_serviceability(body)
        status = str(flat.get("status") or "").upper()
        if flat.get("existing_customer") is True or status == "EXISTING_CUSTOMER":
            return "CURRENT_CUSTOMER", f"API existingCustomer (status={status})"
        if flat.get("serviceable") is False or status in (
            "NOT_SERVICEABLE",
            "OUT_OF_FOOTPRINT",
        ):
            return "PROVIDER_NOT_AVAILABLE", f"API not serviceable (status={status})"
        if flat.get("in_footprint") is False:
            return "PROVIDER_NOT_AVAILABLE", "API inFootPrint=False"
        if flat.get("serviceable") is True or flat.get("in_footprint") is True:
            return "PROSPECT_CUSTOMER", f"API serviceable (status={status})"
    return "", ""
