"""Baseline unit tests for Frontier packaging (no live browser)."""

from __future__ import annotations

import json
import os
import sys

import pytest

CRAWLER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "crawler"))
if CRAWLER not in sys.path:
    sys.path.insert(0, CRAWLER)


def test_frontier_seed_registers():
    from dca_frontier.seeds import frontier_seed_recipe
    from dca_recipe_engine.seeds import get_seed

    recipe = frontier_seed_recipe()
    assert recipe.provider == "frontier"
    assert "frontier.com" in recipe.start_url
    assert [s.name for s in recipe.steps] == [
        "step0",
        "step1_address",
        "step2a",
        "step2b",
        "step3a",
    ]
    assert all(s.vision_agent_enabled is False for s in recipe.steps)
    assert get_seed("frontier").provider == "frontier"


def test_frontier_healer_is_deterministic_only():
    import asyncio

    from dca_recipe_engine.schema import PipelineStepResult
    from dca_recipe_engine.steps.healers import get_healer

    healer = get_healer("frontier")
    assert healer.__class__.__module__.endswith(".frontier")

    async def _run():
        result = PipelineStepResult()
        out = await healer.heal_step0(None, None, result)
        assert out is result
        assert "deterministic-only" in (result.error or "")
        assert result.detection_method == "deterministic"
        assert await healer.heal_step3a_names(None, None, PipelineStepResult()) is None

    asyncio.run(_run())


def test_decode_serviceability_flat():
    from dca_frontier.decoder import decode_scope_from_bodies, decode_serviceability

    body = json.dumps(
        {
            "status": "OK",
            "serviceable": True,
            "inFootPrint": True,
            "existingCustomer": False,
        }
    )
    flat = decode_serviceability(body)
    assert flat["serviceable"] is True
    scope, _ = decode_scope_from_bodies({"serviceability": body})
    assert scope == "PROSPECT_CUSTOMER"


def test_scope_unknown_address_naming():
    from dca_frontier.offer_extractor import determine_scope_from_page

    scope, _ = determine_scope_from_page("We couldn't find that address")
    assert scope == "UNKNOWN_ADDRESS"


def test_ai_agents_config_has_frontier():
    path = os.path.join(CRAWLER, "ai_agents_config", "ai_agents_config.json")
    data = json.load(open(path))
    providers = {p["provider"]: p for p in data["providers"]}
    assert "frontier" in providers
    assert providers["frontier"]["engine"] == "recipe"
    assert providers["frontier"]["diagnose_enabled"] is False
    assert providers["frontier"]["step_defaults"]["vision_agent_enabled"] is False
