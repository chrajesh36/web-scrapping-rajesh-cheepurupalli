"""Generic healer stub — may invoke LLM / vision in the full deadshot engine.

Local stub returns deterministic failures so tests stay offline.
"""

from __future__ import annotations

from typing import Optional

from playwright.async_api import Page

from dca_recipe_engine.pipeline_context import PipelineContext
from dca_recipe_engine.schema import PipelineStepResult


class Healer:
    async def heal_step0(
        self, page: Page, ctx: PipelineContext, result: PipelineStepResult, **kwargs
    ) -> Optional[PipelineStepResult]:
        result.error = "step0 failed (generic stub — no self-heal in this repo)"
        result.detection_method = "deterministic"
        result.elapsed_s = 0.0
        return result
