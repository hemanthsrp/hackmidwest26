"""Tier-1 'deterministic router' from the README, implemented as an
in-process filter for v1 (no Kafka/RabbitMQ/Redis -- see DECISIONS.md: no
broker until the demo actually needs one). Zero-LLM-cost rejection of
unusable payloads before they reach normalization/tagging."""

from ..sources.base import RawRecord

REQUIRED_PAYLOAD_KEYS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "general_news": ("title",),
    "sec_filing": ("form_type",),
    "congressional_disclosure": ("ticker",),
    "social_media": ("title",),
}


def passes_filter(record: RawRecord) -> bool:
    if not record.symbol:
        return False
    required = REQUIRED_PAYLOAD_KEYS_BY_TYPE.get(record.source_type, ())
    return all(record.payload.get(key) for key in required)


def filter_records(records: list[RawRecord]) -> list[RawRecord]:
    return [r for r in records if passes_filter(r)]
