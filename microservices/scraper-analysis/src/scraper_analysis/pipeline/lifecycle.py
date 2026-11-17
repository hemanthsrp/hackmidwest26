"""Evidence and signal lifecycle stages (docs/EVIDENCE_LIFECYCLE_CONTRACT.md).

    fresh --(stale_at passes)--> stale --(archived)--> archived

Stages only move forward. The stored ``lifecycle_status`` is a serving state that a
lifecycle job may advance; the contract requires query-time checks so that an
overdue job "cannot make a stale row look current", so readers take whichever is
further along: the stored state or the one the timestamps imply.

New records get the policy timestamps the lifecycle migration backfilled
(storage/lifecycle_schema.sql): evidence is fresh for 24 hours and stale after 7
days from retrieval, a market signal stale a day after its as-of time.
"""

from datetime import UTC, datetime, timedelta

STAGES = ("fresh", "stale", "archived")
EVIDENCE_FRESH_FOR = timedelta(hours=24)
EVIDENCE_STALE_AFTER = timedelta(days=7)
SIGNAL_STALE_AFTER = timedelta(days=1)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def stage(stored: str | None, stale_at: datetime | None, archived_at: datetime | None, now: datetime) -> str:
    """The furthest stage reached by the stored state or by the timestamps."""
    implied = "fresh"
    if archived_at is not None and _utc(archived_at) <= now:
        implied = "archived"
    elif stale_at is not None and _utc(stale_at) <= now:
        implied = "stale"
    stored = stored if stored in STAGES else "fresh"
    return max(stored, implied, key=STAGES.index)


def with_evidence_policy(evidence) -> None:
    """Fill fresh_until / stale_at from retrieved_at when a source did not set them."""
    retrieved = _utc(evidence.retrieved_at)
    if evidence.fresh_until is None:
        evidence.fresh_until = retrieved + EVIDENCE_FRESH_FOR
    if evidence.stale_at is None:
        evidence.stale_at = retrieved + EVIDENCE_STALE_AFTER


def current_evidence(evidence, now: datetime | None = None):
    """The record with its policy timestamps filled and its stage as of ``now``."""
    with_evidence_policy(evidence)
    evidence.lifecycle_status = stage(
        evidence.lifecycle_status, evidence.stale_at, evidence.archived_at, now or datetime.now(UTC)
    )
    return evidence


def current_signal(signal, now: datetime | None = None):
    if signal.stale_at is None:
        signal.stale_at = _utc(signal.as_of) + SIGNAL_STALE_AFTER
    signal.lifecycle_status = stage(signal.lifecycle_status, signal.stale_at, None, now or datetime.now(UTC))
    return signal
