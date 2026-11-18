#!/usr/bin/env sh
# Rebuild requirements/python.lock: exact versions of every third-party Python
# package, resolved on Linux with Python 3.12 like CI and the Docker images.
# Existing pins are kept unless a pyproject.toml change forces a new one; pass
# --upgrade to move everything to the newest allowed versions.
set -eu
repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
docker run --rm -v "$repo_root:/repo" -w /repo python:3.12-slim sh -c "
  pip install --quiet --root-user-action=ignore uv==0.9.5 &&
  uv pip compile requirements/python.in --output-file requirements/python.lock \
    --python-version 3.12 --python-platform linux --quiet $* \
    --no-emit-package agentic-search --no-emit-package decision-maker \
    --no-emit-package jev-tool --no-emit-package research-api \
    --no-emit-package scraper-analysis --no-emit-package hackmidwest-volatility-surface-builder \
    --no-emit-package yahoo-finance-mcp"
