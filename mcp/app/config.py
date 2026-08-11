"""Configuration.

The MCP server holds no secrets of its own except Mealie's API token, which it
needs for recipe search. It has no database and no token store — see
`app/auth.py` for why.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MISEN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Both reached over the internal compose network; neither is published.
    companion_url: str = "http://companion:8000"
    mealie_url: str = "http://mealie:9000"
    mealie_token: str = ""

    # Generous, because a tool call that times out costs the model a turn and
    # the user a wait. Companion's own Mealie timeout is 15s, so this sits
    # above it: we want Companion's clean 502 rather than our own timeout.
    timeout: float = 25.0

    @property
    def public_url(self) -> str:
        """Advertised as the protected resource in auth metadata."""
        return self.mcp_public_url or "http://localhost:8001"

    mcp_public_url: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
