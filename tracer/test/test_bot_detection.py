"""Tests for restored bot-detection methods + session scoring."""

from __future__ import annotations

import os
import sys

CRAWLER = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "crawler"))
if CRAWLER not in sys.path:
    sys.path.insert(0, CRAWLER)


def test_detection_methods_catalog():
    from dca_bot_detection.methods import DETECTION_METHODS, SCORING_RUBRIC

    assert len(DETECTION_METHODS) >= 5
    assert any(m["id"] == "sensor_abck" for m in DETECTION_METHODS)
    assert "live_session_points" in SCORING_RUBRIC


def test_session_score_abck_fail_and_soft_block():
    from dca_bot_detection.session_score import score_session

    sc = score_session(
        abck_flag="-1",
        address_field_present=True,
        soft_block_technical=True,
        plans_loaded=False,
        scope_reason="Plans did not load after address submission",
    )
    assert sc.detection_score >= 60
    assert "CRITICAL" in sc.verdict or "HIGH" in sc.verdict
    assert sc.abck_validated is False


def test_session_score_validated_with_plans():
    from dca_bot_detection.session_score import score_session

    sc = score_session(
        abck_flag="0",
        address_field_present=True,
        soft_block_technical=False,
        plans_loaded=True,
    )
    assert sc.detection_score <= 20
    assert sc.abck_validated is True


def test_package_exports_logger_and_scorecard():
    from dca_bot_detection import ApiLogger, BotScorecard, score_session

    assert ApiLogger is not None
    assert BotScorecard is not None
    assert callable(score_session)


def test_legacy_shims_resolve():
    legacy = os.path.abspath(os.path.join(CRAWLER, "..", "legacy"))
    if legacy not in sys.path:
        sys.path.insert(0, legacy)
    import api_logger  # noqa: F401
    import behavior  # noqa: F401
    import bot_scorecard  # noqa: F401
