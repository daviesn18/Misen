"""Configuration, read from the environment.

Everything Misen-specific uses the MISEN_ prefix. There is no model API key
here: Misen never calls a model. Planning happens in a Claude Project, which
reaches the MCP server with the member's own token, so the only credentials
this service holds are Mealie's and its own members'.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

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
    # Advertised to members setting up the Claude Project connector; nothing in
    # this service calls it. Companion is the MCP server's backend, not its
    # client, so there is no credential to configure here.
    mcp_url: str = ""

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
