from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from playwright.async_api import Page


@dataclass
class PipelineContext:
    """Shared state for a recipe pipeline run."""

    provider: str
    address: str
    page: Optional[Page] = None
    scope: str = ""
    scope_reason: str = ""
    offers: list[dict[str, Any]] = field(default_factory=list)
    captured_api: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)
