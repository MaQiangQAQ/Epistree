"""Pydantic Settings — all config from environment variables."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Zhihu
    zhihu_access_secret: str = Field(default="", validation_alias="ZHIHU_ACCESS_SECRET")
    zhihu_api_base: str = "https://developer.zhihu.com/api/v1"

    # LLM endpoint (OpenAI-compatible)
    llm_base_url: HttpUrl = Field(
        default=HttpUrl("https://api.openai-next.com/v1"),
        validation_alias="LLM_BASE_URL",
    )
    llm_api_key: str = Field(default="", validation_alias="LLM_API_KEY")
    llm_model: str = Field(default="deepseek-v4-flash", validation_alias="LLM_MODEL")

    # Data persistence
    data_dir: Path = Field(default=Path("./.data"), validation_alias="DATA_DIR")

    # Demo limits
    demo_daily_call_limit: int = Field(default=20, validation_alias="DEMO_DAILY_CALL_LIMIT")
    demo_max_queries: int = Field(default=6, validation_alias="DEMO_MAX_QUERIES")
    demo_max_sources: int = Field(default=12, validation_alias="DEMO_MAX_SOURCES")
    demo_admin_token: str = Field(default="", validation_alias="DEMO_ADMIN_TOKEN")

    # Prompt / schema versioning
    prompt_version: str = "v1"
    graph_schema_version: str = "v1"

    @property
    def has_zhihu_auth(self) -> bool:
        return bool(self.zhihu_access_secret)

    @property
    def has_llm_auth(self) -> bool:
        return bool(self.llm_api_key)

    @property
    def http_cache_path(self) -> Path:
        return self.data_dir / "http_cache"

    @property
    def epistree_db_path(self) -> Path:
        return self.data_dir / "epistree.sqlite"


settings = Settings()
