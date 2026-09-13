"""Validated local API settings; process environment overrides .env."""
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEDIASENSEI_", env_file=".env", extra="ignore")
    workspace: Path = Path(".mediasensei-workspace")
    cors_origins: list[str] = Field(default_factory=list)
    max_upload_bytes: int = Field(default=2 * 1024**3, ge=1)
    zip_max_files: int = Field(default=20_000, ge=1)
    zip_max_total_bytes: int = Field(default=20 * 1024**3, ge=1)

settings = Settings()
settings.workspace = settings.workspace.expanduser().resolve()
