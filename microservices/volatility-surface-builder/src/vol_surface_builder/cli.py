"""Generate local option-volatility charts from sample or explicit live data."""

import argparse
import math
from pathlib import Path

from .data_feed import get_option_data
from .surface_builder import build_surface, compute_surface_statistics
from .visualization import (
    plot_skew_matplotlib,
    plot_skew_plotly,
    plot_surface_matplotlib,
    plot_surface_plotly,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an option-implied volatility surface.")
    parser.add_argument("--source", choices=["sample", "live"], default="sample")
    parser.add_argument("--ticker", default="SPY")
    parser.add_argument("--spot", type=float, default=602.0)
    parser.add_argument("--output-dir", type=Path, default=Path.cwd() / "output")
    parser.add_argument("--no-html", action="store_true")
    args = parser.parse_args()
    ticker = args.ticker.strip().upper()
    if not math.isfinite(args.spot) or args.spot <= 0:
        parser.error("--spot must be a positive finite number")
    if args.source == "sample" and ticker != "SPY":
        parser.error("synthetic sample data is calibrated for SPY only")

    frame, spot = get_option_data(
        source="synthetic" if args.source == "sample" else "live",
        ticker=ticker,
        spot=args.spot,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    strikes, maturities, strike_mesh, maturity_mesh, iv_mesh = build_surface(frame)
    plot_surface_matplotlib(
        strike_mesh, maturity_mesh, iv_mesh, spot, ticker,
        str(args.output_dir / "vol_surface_3d.png"),
    )
    plot_skew_matplotlib(frame, spot, ticker, str(args.output_dir / "vol_skew_2d.png"))
    if not args.no_html:
        plot_surface_plotly(
            strikes, maturities, iv_mesh, spot, ticker,
            str(args.output_dir / "vol_surface_3d.html"),
        )
        plot_skew_plotly(frame, spot, ticker, str(args.output_dir / "vol_skew_2d.html"))
    frame.to_csv(args.output_dir / "option_iv_data.csv", index=False)
    stats = compute_surface_statistics(frame, spot)
    print(f"{ticker}: {stats['n_points']} option-IV points, {stats['n_expiries']} maturities")
    print(f"Mode: {args.source}; charts and data: {args.output_dir}")


if __name__ == "__main__":
    main()
