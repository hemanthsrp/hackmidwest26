import pytest
from pydantic import ValidationError

from scraper_analysis.config import Settings


def test_non_local_database_requires_tls_by_default():
    with pytest.raises(ValidationError, match="sslmode=require"):
        Settings(_env_file=None, database_url="postgresql://folio:secret@database:5432/folio")


def test_compose_database_host_is_allowed_only_with_explicit_local_flag():
    settings = Settings(
        _env_file=None,
        allow_insecure_local_database=True,
        database_url="postgresql://folio:secret@database:5432/folio",
    )
    assert settings.database_url.endswith("@database:5432/folio")


def test_local_flag_does_not_disable_tls_for_other_hosts():
    with pytest.raises(ValidationError, match="sslmode=require"):
        Settings(
            _env_file=None,
            allow_insecure_local_database=True,
            database_url="postgresql://folio:secret@db.example:5432/folio",
        )
