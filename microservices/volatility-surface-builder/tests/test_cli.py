import sys

import pytest

from vol_surface_builder.cli import main


@pytest.mark.parametrize("spot", ["0", "-1", "nan", "inf"])
def test_sample_cli_rejects_non_positive_or_non_finite_spot(monkeypatch, spot: str) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["vol-surface", "--source", "sample", "--ticker", "SPY", "--spot", spot, "--no-html"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
