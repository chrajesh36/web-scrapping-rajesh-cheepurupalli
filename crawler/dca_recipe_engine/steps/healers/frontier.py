"""Frontier healer — deterministic-only.

Never invokes an LLM, never writes recipe_history / Mongo, never calls vision.
On any step failure, return ERROR_PROCESSING immediately.
"""

from __future__ import annotations

from typing import Optional

from playwright.async_api import Page

from dca_recipe_engine.pipeline_context import PipelineContext
from dca_recipe_engine.schema import PipelineStepResult


class Healer:
    """Tier-1 only: no self-heal path for Frontier."""

    async def heal_step0(
        self, page: Page, ctx: PipelineContext, result: PipelineStepResult, **kwargs
    ) -> Optional[PipelineStepResult]:
        result.error = "step0 failed (deterministic-only, no self-heal)"
        result.detection_method = "deterministic"
        result.elapsed_s = 0.0
        return result

    async def heal_step1(
        self, page: Page, ctx: PipelineContext, result: PipelineStepResult, **kwargs
    ) -> Optional[PipelineStepResult]:
        result.error = "step1_address failed (deterministic-only, no self-heal)"
        result.detection_method = "deterministic"
        result.elapsed_s = 0.0
        return result

    async def heal_step2a(
        self, page: Page, ctx: PipelineContext, result: PipelineStepResult, **kwargs
    ) -> Optional[PipelineStepResult]:
        result.error = "step2a failed (deterministic-only, no self-heal)"
        result.detection_method = "deterministic"
        result.elapsed_s = 0.0
        return result

    async def heal_step2b(
        self, page: Page, ctx: PipelineContext, result: PipelineStepResult, **kwargs
    ) -> Optional[PipelineStepResult]:
        result.error = "step2b failed (deterministic-only, no self-heal)"
        result.detection_method = "deterministic"
        result.elapsed_s = 0.0
        return result

    async def heal_step3a_tile(
        self, page: Page, ctx: PipelineContext, result: PipelineStepResult, **kwargs
    ) -> Optional[PipelineStepResult]:
        result.error = "step3a_tile failed (deterministic-only, no self-heal)"
        result.detection_method = "deterministic"
        result.elapsed_s = 0.0
        return result

    async def heal_step3a_names(
        self, page: Page, ctx: PipelineContext, result: PipelineStepResult, **kwargs
    ) -> Optional[PipelineStepResult]:
        return None

    async def heal_step3b_click(
        self, page: Page, ctx: PipelineContext, result: PipelineStepResult, **kwargs
    ) -> Optional[PipelineStepResult]:
        return None

    async def heal_step3b_modal(
        self, page: Page, ctx: PipelineContext, result: PipelineStepResult, **kwargs
    ) -> Optional[PipelineStepResult]:
        return None

    async def heal_step3b_expand(
        self, page: Page, ctx: PipelineContext, result: PipelineStepResult, **kwargs
    ) -> Optional[PipelineStepResult]:
        return None
