import httpx
import pytest
from fastapi.testclient import TestClient
from research_api import v1
from research_api.app import app
from test_v1 import database, headers  # noqa: F401  (database is autouse-style setup for private routes)


class FakeScraper:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, *a, **k):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None):
        self.calls.append((url, params))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def scraper_history(points, status=200):
    request = httpx.Request('GET', 'http://scraper/price-history')
    body = {'interval': '1d', 'price_field': 'close', 'source': 'Yahoo Finance (yfinance)',
            'as_of': points[-1]['t'] if points else None, 'points': points}
    return httpx.Response(status, json=body, request=request)


def test_returns_real_closes_with_source_labels(monkeypatch, database):
    monkeypatch.setenv('SCRAPER_API_URL', 'http://scraper')
    fake = FakeScraper(scraper_history([{'t': '2026-10-08T04:00:00Z', 'close': 100.5}, {'t': '2026-10-09T04:00:00Z', 'close': 101.25}]))
    monkeypatch.setattr(v1.httpx, 'Client', fake)
    body = TestClient(app).get('/v1/stocks/aapl/history?range=1W', headers=headers()).json()
    assert fake.calls == [('http://scraper/price-history', {'symbol': 'AAPL', 'range': '1W'})]
    assert body['data_mode'] == 'live'
    assert body['data']['source'] == 'Yahoo Finance (yfinance)'
    assert [p['close'] for p in body['data']['points']] == [100.5, 101.25]


def test_requires_a_service_assertion(database):
    assert TestClient(app).get('/v1/stocks/AAPL/history').status_code == 401


def test_rejects_bad_symbol_and_range(monkeypatch, database):
    monkeypatch.setenv('SCRAPER_API_URL', 'http://scraper')
    client = TestClient(app)
    assert client.get('/v1/stocks/TOOLONGSYM/history', headers=headers()).status_code == 400
    assert client.get('/v1/stocks/AAPL/history?range=5Y', headers=headers()).status_code == 400


@pytest.mark.parametrize('response', [
    httpx.ConnectError('refused'),
    scraper_history([], 503),
    scraper_history([{'t': '2026-10-09T04:00:00Z', 'close': 1.0}]),
])
def test_never_fabricates_when_the_source_fails(monkeypatch, database, response):
    monkeypatch.setenv('SCRAPER_API_URL', 'http://scraper')
    monkeypatch.setattr(v1.httpx, 'Client', FakeScraper(response))
    assert TestClient(app).get('/v1/stocks/AAPL/history', headers=headers()).status_code == 503


def test_fails_closed_without_a_configured_source(monkeypatch, database):
    monkeypatch.delenv('SCRAPER_API_URL', raising=False)
    assert TestClient(app).get('/v1/stocks/AAPL/history', headers=headers()).status_code == 503
