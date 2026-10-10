from urllib.parse import parse_qs, urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    aws_default_region: str = "us-east-1"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None
    # Newer Claude models on Bedrock require a cross-region inference
    # profile ID ("us." prefix), not the raw model ID -- confirmed via a
    # live invoke_model call against this account.
    bedrock_model_id: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

    # Single server-only connection string per the DB configuration contract
    # (accepted -- see conversation record): one DATABASE_URL, not split
    # host/port/name/user/password fields, so there's no app-level default
    # (e.g. a hardcoded port or a non-enforcing sslmode) to drift from the
    # real provisioned instance. Never log, commit, or expose this value.
    database_url: str | None = None

    @field_validator("database_url")
    @classmethod
    def _require_tls_for_non_local_hosts(cls, v: str | None) -> str | None:
        if not v:
            return v
        host = urlparse(v).hostname
        if host in ("localhost", "127.0.0.1"):
            return v  # local Docker stand-in has no TLS cert configured
        sslmode = parse_qs(urlparse(v).query).get("sslmode", [None])[0]
        if sslmode != "require":
            raise ValueError(
                f"DATABASE_URL must set sslmode=require for non-local hosts (got sslmode={sslmode!r})"
            )
        return v

    akamai_inference_base_url: str | None = None
    akamai_inference_api_key: str | None = None
    akamai_embedding_model: str | None = None
    akamai_chat_model: str | None = None
    akamai_image_model: str | None = None

    reddit_user_agent: str = "scraper-analysis/0.1 (hackathon research demo)"

    news_api_key: str | None = None
    sec_edgar_user_agent: str = "hackmidwest-scraper-analysis <set-contact-email>"

    enable_x_scraper: bool = False
    # Unofficial public .json scraping (no OAuth) -- off by default, see
    # sources/reddit_unofficial.py docstring for the accepted risk tradeoff.
    enable_reddit_scraper: bool = False

    @property
    def akamai_db_configured(self) -> bool:
        return bool(self.database_url)

    @property
    def akamai_inference_configured(self) -> bool:
        return bool(self.akamai_inference_base_url and self.akamai_inference_api_key)

    @property
    def bedrock_configured(self) -> bool:
        return bool(self.aws_access_key_id and self.aws_secret_access_key)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
