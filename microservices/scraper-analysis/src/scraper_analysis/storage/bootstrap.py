"""Idempotently initialize the scraper evidence schema."""

from pathlib import Path

import psycopg

from ..config import get_settings


def initialize() -> None:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required to initialize scraper storage")
    schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
    with psycopg.connect(settings.database_url, autocommit=True) as connection:
        connection.execute(schema)


if __name__ == "__main__":
    initialize()
