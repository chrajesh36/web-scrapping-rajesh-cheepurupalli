"""Provider healer loader — mirrors deadshot-plugins-ai behavior.

Dynamically imports ``dca_recipe_engine.steps.healers.<provider>``.
Falls back to ``generic`` when no provider-specific module exists.
"""

from __future__ import annotations

import importlib
from typing import Any


def get_healer(provider: str) -> Any:
    name = (provider or "").strip().lower().replace("-", "_")
    if not name:
        name = "generic"
    try:
        mod = importlib.import_module(f"dca_recipe_engine.steps.healers.{name}")
        return mod.Healer()
    except ModuleNotFoundError:
        from dca_recipe_engine.steps.healers import generic

        return generic.Healer()
