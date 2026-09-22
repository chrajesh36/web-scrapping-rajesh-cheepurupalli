"""Shim — re-export full dca_bot_detection.api_logger module (incl. _private helpers)."""
from __future__ import annotations

import importlib
import os
import sys

_CRAWLER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "crawler")
if _CRAWLER not in sys.path:
    sys.path.insert(0, _CRAWLER)

_mod = importlib.import_module("dca_bot_detection.api_logger")
sys.modules[__name__] = _mod
