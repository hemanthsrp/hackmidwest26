# Import and integration notes

Imported into Hack Midwest on 2026-10-10 from `vol-surface-builder-main` commit `4612f97`. The original repository remains unchanged.

| Source | Hack Midwest location |
|---|---|
| `src/*.py` | `../src/vol_surface_builder/*.py` |
| `tests/*.py` | `../tests/*.py` |
| `notebooks/vol_surface_analysis.ipynb` | `../notebooks/vol_surface_analysis.ipynb` |
| `docs/methodology.md` | `methodology.md` |
| `CHANGELOG.md` | `CHANGELOG.md` |
| `README.md` | `original-project-readme.md` (historical copy); current instructions in `../README.md` |

The original `main.py`, `setup.py`, and `requirements.txt` were adapted to a package CLI and `pyproject.toml`. The data CSV and chart files were generated output; run the CLI to reproduce them. The notebook imports the installed `vol_surface_builder` package.

Integration changes are limited to packaging, a local HTTP boundary, an isolated random generator for synthetic data, output-path handling, and documentation. The option diagnostics remain separate from Hack Midwest's stock research assessment. A future frontend may display a volatility chart, but the team must first agree on the chart contract, data rights, freshness rules, and whether this signal belongs in the MVP.
