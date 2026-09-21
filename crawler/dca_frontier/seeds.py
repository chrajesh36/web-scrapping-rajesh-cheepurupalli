"""Frontier navigation recipe (Playwright / dca_recipe_engine).

Ports Phase 1–3 address-check flow from legacy frontier_extract.py.
Tier-1 deterministic only — vision_agent_enabled is False on every step.
"""

from __future__ import annotations

from dca_recipe_engine.schema import ProviderRecipe, RecipeAction, StepRecipe
from dca_recipe_engine.seeds import register_seed

START_URL = "https://frontier.com/shop/internet"
BUY_URL = "https://frontier.com/buy"


def frontier_seed_recipe() -> ProviderRecipe:
    return ProviderRecipe(
        provider="frontier",
        start_url=START_URL,
        meta={
            "buy_url": BUY_URL,
            "engine": "recipe",
            "tier": 1,
            "llm_calls": 0,
        },
        steps=[
            StepRecipe(
                name="step0",
                vision_agent_enabled=False,
                actions=[
                    RecipeAction(action="goto", url=START_URL),
                    RecipeAction(
                        action="dismiss",
                        text="Accept All",
                        optional=True,
                        timeout_ms=4000,
                    ),
                    RecipeAction(
                        action="dismiss",
                        text="Close",
                        optional=True,
                        timeout_ms=2000,
                    ),
                ],
                success_validator="page_loaded",
            ),
            StepRecipe(
                name="step1_address",
                vision_agent_enabled=False,
                actions=[
                    # Prefer /buy address form when shop page has no field
                    RecipeAction(
                        action="goto",
                        url=BUY_URL,
                        optional=True,
                        meta={"fallback_if_missing": "#street-address"},
                    ),
                    RecipeAction(
                        action="type",
                        selector="#street-address",
                        value="{{address}}",
                        meta={
                            "alt_selectors": [
                                'input[placeholder*="Street Address" i]',
                                'input[placeholder*="Enter your address" i]',
                                'input[aria-label*="address" i]',
                                "input.address-form__input",
                            ],
                            "clear_first": True,
                            "use_native_value_setter": True,
                        },
                    ),
                    RecipeAction(
                        action="select_suggestion",
                        selector='[role="option"]',
                        timeout_ms=5000,
                        optional=True,
                        meta={"match_address_tokens": True},
                    ),
                    RecipeAction(
                        action="click",
                        text="CHECK AVAILABILITY",
                        meta={
                            "alt_texts": [
                                "Check availability",
                                "Check Availability",
                            ]
                        },
                    ),
                ],
                success_validator="address_submitted",
            ),
            StepRecipe(
                name="step2a",
                vision_agent_enabled=False,
                actions=[
                    RecipeAction(
                        action="wait_for",
                        timeout_ms=45000,
                        meta={
                            "any_of_body": [
                                "are you moving to this address",
                                "view plan",
                                "add to cart",
                                "/mo",
                                "technical difficulties",
                                "allconnect.com",
                            ]
                        },
                    ),
                    # Prospect path when mover modal appears
                    RecipeAction(
                        action="click",
                        text="YES, I'M MOVING",
                        optional=True,
                        timeout_ms=5000,
                    ),
                ],
                success_validator="plans_or_scope_signal",
            ),
            StepRecipe(
                name="step2b",
                vision_agent_enabled=False,
                actions=[
                    RecipeAction(
                        action="wait_for",
                        selector='[class*="plan" i], [data-testid*="plan" i], [class*="card" i]',
                        timeout_ms=20000,
                        optional=True,
                    ),
                ],
                success_validator="plans_page",
            ),
            StepRecipe(
                name="step3a",
                vision_agent_enabled=False,
                actions=[
                    RecipeAction(
                        action="extract_offers",
                        meta={"module": "dca_frontier.offer_extractor"},
                    ),
                ],
                success_validator="offers_extracted",
            ),
        ],
    )


register_seed("frontier", frontier_seed_recipe)
