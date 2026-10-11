from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def no_live_providers(monkeypatch):
    """Keep every test offline: no evidence store from the shell, no cached decision maker."""
    from research_api import assessment

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("VOL_SURFACE_URL", raising=False)
    assessment.reset()
    yield
    assessment.reset()
