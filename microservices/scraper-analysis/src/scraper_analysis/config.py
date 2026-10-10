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

    akamai_db_host: str | None = None
    akamai_db_port: int = 5432
    akamai_db_name: str | None = None
    akamai_db_user: str | None = None
    akamai_db_password: str | None = None

    akamai_inference_base_url: str | None = None
    akamai_inference_api_key: str | None = None
    akamai_embedding_model: str | None = None
    akamai_chat_model: str | None = None
    akamai_image_model: str | None = None

    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = "scraper-analysis/0.1"

    news_api_key: str | None = None
    sec_edgar_user_agent: str = "hackmidwest-scraper-analysis <set-contact-email>"

    enable_x_scraper: bool = False

    @property
    def akamai_db_configured(self) -> bool:
        return bool(self.akamai_db_host and self.akamai_db_name and self.akamai_db_user)

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
