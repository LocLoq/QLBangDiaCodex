from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_prefix="NORMASTORE_",
        extra="ignore",
    )

    database_url: str = "mysql+pymysql://root:@127.0.0.1:3306/normastore_db?charset=utf8mb4"
    tmdb_api_key: str | None = None
    gemini_api_key: str | None = None
    gemini_embedding_model: str = "gemini-embedding-001"
    gemini_embedding_dimensions: int = 768
    gemini_generation_model: str = "gemini-3.5-flash-lite"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_from: str | None = None
    smtp_starttls: bool = True
    app_name: str = "NormaStore"
    cache_dir: Path = Path("cache")
