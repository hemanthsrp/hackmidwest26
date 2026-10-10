"""Reddit adapter via public, unauthenticated .json listing endpoints --
NOT the official API.

Why: Reddit closed self-service OAuth app registration in Nov 2025 (the
"Responsible Builder Policy"). New API access now requires a manual review
that commonly denies AI/LLM use cases with no appeal and no fixed
turnaround -- not viable to depend on for a hackathon. See the conversation
record for the full decision.

Risk accepted explicitly by the user: this reads public, unauthenticated
endpoints, which carries real ToS/rate-limit/ban risk (ToS violation,
possible IP block). To keep that risk contained and visible:
  - Off by default. Only runs when ENABLE_REDDIT_SCRAPER=true.
  - Isolated in this module -- disabling it doesn't touch anything else.
  - A descriptive User-Agent is sent (Reddit rate-limits generic/missing
    UAs more aggressively); no attempt is made to evade rate limiting or
    blocking if it happens.
"""

from datetime import datetime, timezone
from typing import ClassVar

import httpx

from ..config import get_settings
from ..pipeline.symbol_match import matches_symbol
from .base import RawRecord, SourceAdapter, SourceUnavailableError

SUBREDDITS = ["wallstreetbets", "stocks"]
LISTING_URL = "https://www.reddit.com/r/{subreddit}/new.json?limit=25"

# Engagement-velocity proxy for the README's "karma/score thresholds" --
# the public listing endpoint doesn't expose author karma/account-age
# (that needs a separate per-author call), so score/comment count on the
# post itself stands in for now. Documented approximation, not hidden.
MIN_SCORE = 5


class RedditUnofficialAdapter(SourceAdapter):
    name: ClassVar[str] = "reddit"
    source_type: ClassVar[str] = "social_media"
    fixture_file: ClassVar[str] = "reddit_sample.json"

    def fetch_live(self, symbol: str) -> list[RawRecord]:
        settings = get_settings()
        if not settings.enable_reddit_scraper:
            raise SourceUnavailableError("ENABLE_REDDIT_SCRAPER is false")

        headers = {"User-Agent": settings.reddit_user_agent}
        now = datetime.now(timezone.utc)
        records: list[RawRecord] = []
        errors = 0
        for subreddit in SUBREDDITS:
            try:
                resp = httpx.get(
                    LISTING_URL.format(subreddit=subreddit), headers=headers, timeout=10.0
                )
                resp.raise_for_status()
                posts = resp.json()["data"]["children"]
            except (httpx.HTTPError, KeyError, ValueError):
                errors += 1
                continue

            for post in posts:
                data = post.get("data", {})
                title = data.get("title", "")
                selftext = data.get("selftext", "")
                if data.get("score", 0) < MIN_SCORE:
                    continue
                if not matches_symbol(f"{title} {selftext}", symbol):
                    continue
                created = data.get("created_utc")
                published_at = datetime.fromtimestamp(created, tz=timezone.utc) if created else None
                records.append(
                    RawRecord(
                        source_name=f"r/{subreddit}",
                        source_type=self.source_type,
                        symbol=symbol,
                        payload={
                            "title": title,
                            "description": selftext[:500],
                            "score": data.get("score"),
                            "num_comments": data.get("num_comments"),
                        },
                        retrieved_at=now,
                        published_at=published_at,
                        observed_at=published_at,
                        url=f"https://www.reddit.com{data.get('permalink', '')}" if data.get("permalink") else None,
                    )
                )

        if errors == len(SUBREDDITS):
            raise SourceUnavailableError("all subreddit listings unreachable")
        return records
