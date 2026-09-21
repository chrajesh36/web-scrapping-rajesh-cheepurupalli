from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class RecipeAction:
    """One declarative UI / navigation action inside a step."""

    action: str
    selector: str = ""
    text: str = ""
    value: str = ""
    url: str = ""
    timeout_ms: int = 10000
    optional: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepRecipe:
    """A named pipeline step (step0, step1_address, step2a, ...)."""

    name: str
    actions: list[RecipeAction] = field(default_factory=list)
    success_validator: str = ""
    vision_agent_enabled: bool = False
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderRecipe:
    """Full provider recipe: start URL + ordered steps."""

    provider: str
    start_url: str
    steps: list[StepRecipe] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineStepResult:
    """Result returned by a healer / step runner."""

    ok: bool = False
    error: Optional[str] = None
    detection_method: str = "deterministic"
    elapsed_s: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)
