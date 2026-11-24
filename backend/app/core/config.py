"""Centralised application settings. All configuration is read here, never ad hoc."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HAL_", env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = "sqlite:///./hal.db"
    data_dir: Path = Path("../data")
    max_upload_mb: int = Field(50, ge=1)
    max_zip_uncompressed_mb: int = Field(500, ge=1)
    max_zip_entries: int = Field(500, ge=1)
    reviewer_tokens: str = ""
    offline: bool = True

    @computed_field  # type: ignore[prop-decorator]
    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    @property
    def reviewer_token_map(self) -> dict[str, str]:
        """token -> reviewer_id. Empty map means nobody may submit review decisions."""
        mapping: dict[str, str] = {}
        for pair in filter(None, (p.strip() for p in self.reviewer_tokens.split(","))):
            reviewer_id, _, token = pair.partition(":")
            if reviewer_id and token:
                mapping[token] = reviewer_id
        return mapping

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"


@lru_cache
def get_settings() -> Settings:
    return Settings()
