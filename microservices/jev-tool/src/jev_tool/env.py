"""Optional .env loading, so callers do not have to export variables by hand."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


def load_env(path: Path | str | None = None) -> Path | None:
    """Read KEY=VALUE lines into the environment. Variables that are already set win.

    Looks at `path`, else `JEV_ENV_FILE`, else `.env` in the jev-tool folder. Returns the
    file that was read, or None if there was none.
    """
    env_file = Path(path or os.environ.get("JEV_ENV_FILE") or DEFAULT_ENV_FILE)
    if not env_file.is_file():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip().strip("'\"")
        if name and value and name not in os.environ:
            os.environ[name] = value
    return env_file
