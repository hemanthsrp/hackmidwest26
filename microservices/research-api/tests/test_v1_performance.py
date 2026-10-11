import threading
import time

from fastapi.testclient import TestClient

from research_api import v1
from research_api.app import app
from test_v1 import SECRET, database, headers  # noqa: F401  (shared auth helpers and DB fixture)


def _records(counter):
    def fake(symbol):
        counter.append(symbol)
        time.sleep(0.05)
        return [], []
    return fake


def test_repeat_stock_reads_hit_the_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(v1, 'source_records', _records(calls))
    client = TestClient(app)
    for _ in range(3):
        assert client.get('/v1/stocks/NVDA', headers=headers()).status_code == 200
    assert calls == ['NVDA']


def test_cache_can_be_disabled(monkeypatch):
    calls = []
    monkeypatch.setenv('V1_ASSESS_CACHE_SECONDS', '0')
    monkeypatch.setattr(v1, 'source_records', _records(calls))
    client = TestClient(app)
    client.get('/v1/stocks/NVDA', headers=headers())
    client.get('/v1/stocks/NVDA', headers=headers())
    assert calls == ['NVDA', 'NVDA']


def test_concurrent_misses_share_one_fetch(monkeypatch):
    calls = []
    monkeypatch.setattr(v1, 'source_records', _records(calls))
    threads = [threading.Thread(target=v1.assess_cached, args=('AAPL',)) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert calls == ['AAPL']


def test_failures_are_not_cached(monkeypatch):
    attempts = []

    def flaky(symbol):
        attempts.append(symbol)
        if len(attempts) == 1:
            raise v1.HTTPException(503, 'Research source unavailable')
        return [], []
    monkeypatch.setattr(v1, 'source_records', flaky)
    client = TestClient(app)
    assert client.get('/v1/stocks/MSFT', headers=headers()).status_code == 503
    assert client.get('/v1/stocks/MSFT', headers=headers()).status_code == 200


def test_home_feed_writes_only_changed_labels(monkeypatch):
    snapshot = {'assessment': {'label': 'buy'}, 'evidence': [{'id': 'e'}], 'signals': [], 'data_mode': 'live', 'snapshot': {'as_of': 'x'}}
    monkeypatch.setattr(v1, 'assess_cached', lambda symbol: snapshot)
    writes = []
    real = v1.storage.write
    monkeypatch.setattr(v1.storage, 'write', lambda uid, kind, key, value: (writes.append((kind, key)), real(uid, kind, key, value))[1])
    client = TestClient(app)
    assert client.get('/v1/home-feed', headers=headers()).status_code == 200
    first = [w for w in writes if w[0] == 'last_assessment']
    assert len(first) == len(v1.UNIVERSE)
    writes.clear()
    client.get('/v1/home-feed', headers=headers())
    assert [w for w in writes if w[0] == 'last_assessment'] == []
