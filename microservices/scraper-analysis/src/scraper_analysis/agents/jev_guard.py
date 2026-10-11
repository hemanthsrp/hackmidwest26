"""Optional Jev review of a generated briefing (shared ``microservices/jev-tool``).

The synthesis agent's prompt forbids recommendations and invented facts, and
its citations are verified by ID. This adds a second, independent check of the
*text*: is each point backed by what its cited evidence says, and does the
briefing read as personal advice or a promised outcome.

Purely advisory and additive: it never edits or drops a point. Findings are
returned for ``meta["jev_review"]`` and as extra ``warnings``. With JEV_ENABLED
unset it returns None and the briefing is exactly what it was before.

Scope: only points that cite news or social records are checked, against those
records' ``title`` and ``summary``. Points resting on filings, congressional
disclosures or quantitative signals are not checked: their facts live in
structured ``details`` and numbers, which this comparison cannot see (in live
runs it flagged correct filing points almost every time). These are heuristic
model judgments, not verification.
"""

import logging

from ..config import get_settings
from ..models.briefing import Briefing
from ..models.evidence import Evidence
from ..pipeline.jev_judge import JUDGED_SOURCE_TYPES, _get_tool
from ..sources.base import describe_exception, sanitize_error

logger = logging.getLogger(__name__)

SUPPORT_FLOOR = 0.3
FLAG_THRESHOLD = 0.5


def review_briefing(briefing: Briefing, evidence: list[Evidence], tool=None) -> dict | None:
    if tool is None:
        if not get_settings().jev_configured:
            return None
        try:
            tool = _get_tool()
        except ImportError:
            logger.warning("JEV_ENABLED is set but jev-tool is not installed; skipping briefing review")
            return None
        except Exception as exc:
            # A constructor that raises: same fallback (briefing unreviewed). Never exc_info.
            logger.warning("jev tool could not be built; returning the briefing unreviewed: %s",
                           describe_exception(exc))
            return None
    try:
        return _review(briefing, evidence, tool)
    except Exception as exc:
        # Never exc_info: provider exception text can carry the API key or a tokened URL.
        logger.warning("jev briefing review failed; returning the briefing unreviewed: %s", describe_exception(exc))
        return None


def _unavailable(error: str | None) -> dict:
    return {"engine": "unavailable", "error": sanitize_error(error) if error else None, "warnings": []}


def _review(briefing: Briefing, evidence: list[Evidence], tool) -> dict:
    by_id = {e.id: e for e in evidence}
    points: list[dict] = []
    warnings: list[str] = []
    advice = promise = 0.0
    model = version = None

    for index, point in enumerate(briefing.points):
        cited = [
            by_id[i]
            for i in point.evidence_ids
            if i in by_id and by_id[i].source_type in JUDGED_SOURCE_TYPES
        ]
        if not cited:
            points.append(
                {"index": index, "status": "not_checked", "reason": "cites no news or social records"}
            )
            continue
        check = tool.check_explanation(
            point.text, [{"id": e.id, "title": e.title, "summary": e.summary} for e in cited]
        )
        if check.engine != "jev":
            return _unavailable(check.error)
        model, version = check.model, check.question_set_version
        advice, promise = max(advice, check.personal_advice), max(promise, check.promises_outcome)
        weakest = min(check.claims, key=lambda c: c.supported, default=None)
        supported = weakest.supported if weakest else None
        points.append(
            {"index": index, "status": "checked", "supported": supported, "evidence_checked": len(cited)}
        )
        if supported is not None and supported < SUPPORT_FLOOR:
            warnings.append(
                f"jev: point {index + 1} may not be supported by its cited evidence "
                f"({supported:.2f}): {weakest.text[:80]!r}"
            )

    framing = tool.check_explanation(f"{briefing.headline} {briefing.uncertainty}", [])
    if framing.engine != "jev":
        return _unavailable(framing.error)
    model, version = framing.model, framing.question_set_version
    advice, promise = max(advice, framing.personal_advice), max(promise, framing.promises_outcome)

    if advice >= FLAG_THRESHOLD:
        warnings.append(f"jev: briefing text may read as personal investment advice ({advice:.2f})")
    if promise >= FLAG_THRESHOLD:
        warnings.append(f"jev: briefing text may present a future outcome as certain ({promise:.2f})")
    return {
        "engine": "jev",
        "model": model,
        "question_set_version": version,
        "points": points,
        "personal_advice": advice,
        "promises_outcome": promise,
        "thresholds": {"supported_below": SUPPORT_FLOOR, "flag_at_or_above": FLAG_THRESHOLD},
        "warnings": warnings,
    }
