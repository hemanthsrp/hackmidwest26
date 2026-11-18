"""Write one record of every kind Folio stores into a freshly migrated database.

CI runs this after applying every schema owner in deploy order (twice, as a
redeploy does), so a table or column one service writes but no migration
creates fails here instead of on a new install. Needs DATABASE_URL and
RESEARCH_DATABASE_URL; see .github/workflows/ci.yml (database-schema job).
"""

import os
from datetime import datetime, timezone

from research_api import storage as research_storage
from research_api.quant import persist_snapshot
from scraper_analysis.models.evidence import Evidence
from scraper_analysis.models.signal import Signal
from scraper_analysis.pipeline.dedup import assign_stable_ids
from scraper_analysis.storage.store import get_store

now = datetime.now(timezone.utc)
store = get_store()

evidence = Evidence(symbol="AAPL", title="Schema check", source_name="CI", source_type="general_news",
                    source_url="https://example.com/schema-check", observed_at=now, retrieved_at=now, data_mode="live")
assign_stable_ids([evidence])
store.save_evidence([evidence])
assert [e.id for e in store.query_evidence("AAPL")] == [evidence.id], "evidence was not stored"

store.save_signals([Signal(symbol="AAPL", name="30-day price change", value=1.5, unit="percent", window="30d",
                           as_of=now, source="Yahoo Finance", data_mode="live")])
assert len(store.query_signals("AAPL")) == 1, "signal was not stored"

snapshot = {"symbol": "AAPL", "source": "Yahoo Finance option chain", "data_mode": "live",
            "retrieved_at": now.isoformat(), "statistics": {}}
assert persist_snapshot(snapshot, database_url=os.environ["DATABASE_URL"]) is not None, "volatility snapshot was not stored"

research_storage.write("schema-check-user", "preferences", "current", {"horizon": "30d"})
assert research_storage.read("schema-check-user", "preferences"), "research record was not stored"

print("every record kind stored")
