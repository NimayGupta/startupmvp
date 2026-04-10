from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "postgres://postgres:postgres@localhost:5432/discount_optimizer"
    db_encryption_key: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # LLM
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    llm_provider: Literal["anthropic", "openai"] = "anthropic"

    # Shopify
    shopify_api_key: str = ""
    shopify_api_secret: str = ""

    # Internal
    internal_api_key: str = ""
    engine_version: Literal["rules_v1", "bandit_v1"] = "rules_v1"

    # Observability
    sentry_dsn: str = ""
    langchain_api_key: str = ""
    langchain_tracing_v2: bool = False

    python_env: Literal["development", "staging", "production"] = "development"


settings = Settings()
