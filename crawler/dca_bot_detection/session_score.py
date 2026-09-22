"""Lightweight detection score for a live Frontier address session.

Complements BotScorecard (Excel/ApiLogger). Used when we have per-check
signals (_abck, field present, soft-block text, plans) without a full
network capture workbook.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from dca_bot_detection.methods import SCORING_RUBRIC


@dataclass
class SessionDetectionScore:
    """0 = undetected / offers OK, 100 = fully blocked."""

    detection_score: int = 0
    verdict: str = "UNKNOWN"
    abck_flag: str = ""
    abck_validated: bool = False
    address_field_present: bool = True
    soft_block_technical: bool = False
    plans_loaded: bool = False
    mover_seen: bool = False
    multipage_warmup: bool = True
    fresh_profile: bool = True
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_session(
    *,
    abck_flag: str = "",
    address_field_present: bool = True,
    soft_block_technical: bool = False,
    plans_loaded: bool = False,
    mover_seen: bool = False,
    multipage_warmup: bool = True,
    fresh_profile: bool = True,
    scope_reason: str = "",
) -> SessionDetectionScore:
    pts = SCORING_RUBRIC["live_session_points"]
    score = 0
    notes: list[str] = []

    flag = (abck_flag or "").strip()
    validated = flag == "0"
    if not flag:
        score += pts["abck_missing"]
        notes.append("_abck missing/unknown (+10)")
    elif not validated:
        score += pts["abck_not_validated"]
        notes.append(f"_abck={flag} not validated (+40)")
    else:
        notes.append("_abck=0 validated (ok)")

    if not address_field_present:
        score += pts["no_address_field"]
        notes.append("address field missing — soft/hard bot block (+30)")

    if soft_block_technical:
        score += pts["soft_block_technical"]
        notes.append("technical-difficulties soft-block (+20)")

    reason_l = (scope_reason or "").lower()
    if (
        not plans_loaded
        and address_field_present
        and (
            "plans did not load" in reason_l
            or "no pricing" in reason_l
            or "technical difficulties" in reason_l
        )
    ):
        score += pts["no_plans_after_submit"]
        notes.append("plans/API empty after submit (+15)")

    if mover_seen and not plans_loaded:
        notes.append("mover modal seen — footprint OK; offer API still blocked")

    score = min(score, 100)
    verdict = "UNKNOWN"
    for band in SCORING_RUBRIC["bands"]:
        if score <= band["max"]:
            verdict = band["verdict"]
            break

    return SessionDetectionScore(
        detection_score=score,
        verdict=verdict,
        abck_flag=flag,
        abck_validated=validated,
        address_field_present=address_field_present,
        soft_block_technical=soft_block_technical,
        plans_loaded=plans_loaded,
        mover_seen=mover_seen,
        multipage_warmup=multipage_warmup,
        fresh_profile=fresh_profile,
        notes=notes,
    )
