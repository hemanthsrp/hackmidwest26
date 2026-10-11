from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def no_live_providers(monkeypatch):
    """Keep every test offline: no evidence store from the shell, no cached decision maker."""
    from research_api import assessment
    from research_api.app import clear_assessment_cache

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("VOL_SURFACE_URL", raising=False)
    monkeypatch.delenv("ROBINHOOD_MCP_ENABLED", raising=False)
    monkeypatch.delenv("BROKER_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("ROBINHOOD_REDIRECT_URI", raising=False)
    from research_api import recommendations

    from research_api import v1

    assessment.reset()
    recommendations.reset()
    clear_assessment_cache()
    v1.clear_assess_cache()
    yield
    assessment.reset()
    recommendations.reset()
    clear_assessment_cache()
    v1.clear_assess_cache()
