"""Lightweight recipe-engine stubs matching deadshot-plugins-ai interfaces.

When this package is copied into apm0015603-deadshot-plugins-ai, the real
engine replaces these stubs. Local development can import the same names.
"""

from dca_recipe_engine.schema import (
    PipelineStepResult,
    ProviderRecipe,
    RecipeAction,
    StepRecipe,
)

__all__ = [
    "PipelineStepResult",
    "ProviderRecipe",
    "RecipeAction",
    "StepRecipe",
]
