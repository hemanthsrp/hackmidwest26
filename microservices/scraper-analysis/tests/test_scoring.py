from datetime import datetime, timezone

from scraper_analysis.models.evidence import Evidence
from scraper_analysis.pipeline.scoring import apply_credibility, noise_penalty

NOW = datetime(2026, 10, 10, tzinfo=timezone.utc)


def ev(title, source, source_type="general_news", **kw):
    return Evidence(
        symbol="AAPL", title=title, source_name=source, source_type=source_type,
        retrieved_at=NOW, **kw,
    )


def test_known_outlet_gets_its_authority_prior():
    item = ev("Apple edges higher", "CNBC")
    apply_credibility([item])
    assert item.credibility.source_reliability_weight == 0.85


def test_unknown_outlet_and_social_defaults():
    news = ev("Apple edges higher", "randomblog.example")
    post = ev("AAPL to the moon", "r/stocks", source_type="social_media")
    apply_credibility([news, post])
    assert news.credibility.source_reliability_weight == 0.5
    assert post.credibility.source_reliability_weight == 0.3
    assert post.credibility.overall_score < news.credibility.overall_score


def test_corroboration_across_independent_sources_raises_score():
    a = ev("Apple supplier flags component constraints for holiday quarter", "CNBC")
    b = ev("Apple supplier flags component constraints holiday quarter", "MarketWatch")
    c = ev("Apple supplier flags component constraints for holiday quarter", "Yahoo Finance")
    lone = ev("Apple supplier flags component constraints for holiday quarter", "CNBC")
    apply_credibility([a, b, c])
    apply_credibility([lone])
    assert a.credibility.overall_score > lone.credibility.overall_score


def test_same_source_does_not_corroborate_itself():
    a = ev("Apple supplier flags component constraints", "CNBC")
    b = ev("Apple supplier flags component constraints", "CNBC")
    apply_credibility([a, b])
    lone = ev("Apple supplier flags component constraints", "CNBC")
    apply_credibility([lone])
    assert a.credibility.overall_score == lone.credibility.overall_score


def test_verified_filings_are_untouched():
    filing = ev("Apple filed Form 4", "SEC EDGAR", source_type="sec_filing")
    filing.credibility.verified_filing = True
    filing.credibility.overall_score = 1.0
    apply_credibility([filing])
    assert filing.credibility.overall_score == 1.0
    assert filing.credibility.source_reliability_weight is None


def test_sensational_title_is_penalised():
    calm = ev("Apple edges higher", "CNBC")
    loud = ev("APPLE CRASHES!!", "CNBC")
    assert noise_penalty(calm) == 0.0
    assert noise_penalty(loud) > 0.0
    apply_credibility([calm, loud])
    assert loud.credibility.overall_score < calm.credibility.overall_score


def test_score_never_exceeds_one():
    items = [ev("Apple beats estimates strongly", s) for s in ("CNBC", "MarketWatch", "Yahoo Finance")]
    apply_credibility(items)
    assert all(i.credibility.overall_score <= 1.0 for i in items)
