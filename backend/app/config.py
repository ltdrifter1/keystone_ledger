from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KEYSTONE_")

    app_name: str = "Keystone Ledger"
    app_version: str = "0.1.0"
    debug: bool = True
    database_url: str = f"sqlite:///{Path(__file__).resolve().parent.parent / 'data' / 'keystone.db'}"
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
    ]
    default_reporting_currency: str = "CAD"
    audit_enabled: bool = True
    # demo | csv_folder | composite (csv overlay, then demo catalog)
    feed_provider: str = "composite"
    attachments_dir: str = str(Path(__file__).resolve().parent.parent / "data" / "attachments")
    feeds_dir: str = str(Path(__file__).resolve().parent.parent / "data" / "feeds")


@lru_cache
def get_settings() -> Settings:
    return Settings()
