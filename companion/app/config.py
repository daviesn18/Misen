"""Configuration, read from the environment.

Everything Misen-specific uses the MISEN_ prefix. ANTHROPIC_API_KEY is the one
exception — it keeps its conventional name so the Anthropic SDK and any local
tooling pick it up without a second variable holding the same secret.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MISEN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Storage ---------------------------------------------------------
    db_path: Path = Path("./misen.db")

    # --- Locale ----------------------------------------------------------
    # Drives week boundaries and the hour plan reminders fire. Overridden
    # per household by households.timezone once phase 1 lands the schema;
    # this is the fallback for a household that has not set one.
    tz: str = "America/New_York"

    # --- Mealie ----------------------------------------------------------
    mealie_url: str = "http://mealie:9000"
    mealie_token: str = ""

    # --- MCP -------------------------------------------------------------
    mcp_url: str = ""
    mcp_token: str = ""

    # --- Basil -----------------------------------------------------------
    chat_model: str = "claude-opus-5"
    daily_message_cap: int = 100
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
