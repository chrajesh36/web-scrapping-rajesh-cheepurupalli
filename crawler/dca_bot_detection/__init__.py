"""Bot detection logging, scoring, and behavioral helpers.

Promoted from research scripts so methods + scorecards are first-class —
not buried under legacy/.

Modules:
  - api_logger: network capture, sensor POSTs, _abck tracking, Excel export
  - bot_scorecard: 0–100 detection score from ApiLogger / Excel
  - behavior: Bezier mouse, log-normal typing, warmup (Playwright + nodriver)
  - methods: catalog of Akamai/vendor detection methods we counter
  - session_score: lightweight live score during address checks
"""

from dca_bot_detection.api_logger import ApiLogger, SensorEvent
from dca_bot_detection.bot_scorecard import BotScorecard, ScorecardMetric
from dca_bot_detection.session_score import SessionDetectionScore, score_session

__all__ = [
    "ApiLogger",
    "SensorEvent",
    "BotScorecard",
    "ScorecardMetric",
    "SessionDetectionScore",
    "score_session",
]
