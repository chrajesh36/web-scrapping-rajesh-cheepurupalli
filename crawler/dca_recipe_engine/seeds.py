"""Seed registry helpers (stub for deadshot parity)."""

from __future__ import annotations

from typing import Callable

from dca_recipe_engine.schema import ProviderRecipe

_REGISTRY: dict[str, Callable[[], ProviderRecipe]] = {}


def register_seed(provider: str, factory: Callable[[], ProviderRecipe]) -> None:
    _REGISTRY[provider.lower()] = factory


def get_seed(provider: str) -> ProviderRecipe:
    key = provider.lower()
    if key not in _REGISTRY:
        raise KeyError(f"No seed registered for provider={provider!r}")
    return _REGISTRY[key]()
