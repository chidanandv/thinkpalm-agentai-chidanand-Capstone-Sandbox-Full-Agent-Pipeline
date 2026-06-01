from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = ""
    database_path: str = "./data/memory.db"
    llm_model: str = "claude-sonnet-4-20250514"
    llm_timeout_seconds: float = 25.0
    llm_max_retries: int = 1
    skip_llm: bool = False
    fuel_variance_threshold_pct: float = 8.0
    schedule_slippage_hours: float = 12.0

    @property
    def db_path(self) -> Path:
        return Path(self.database_path)


settings = Settings()
