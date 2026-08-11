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
    # Only the URL. Phase 5 passes the *caller's own* member token to Anthropic
    # as mcp_servers[].authorization_token — Companion already holds it in the
    # request it is serving — so there is no second secret to configure here.
    mcp_url: str = ""

    # --- Basil -----------------------------------------------------------
    chat_model: str = "claude-opus-5"
    daily_message_cap: int = 100
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    # Room for a full week of planning in one turn: fourteen menu reads and
    # writes plus a shopping build is a lot of tool traffic, and a turn that
    # runs out of tokens mid-plan leaves the menu half-written.
    chat_max_tokens: int = 16000
    # Turns of history replayed to the model. PRD §7: past roughly this many,
    # a conversation has stopped being about dinner.
    chat_history_turns: int = 40

    # --- Instacart (optional) --------------------------------------------
    # Misen contains no Instacart code (PRD decision 2). Ordering happens by
    # attaching Instacart's own MCP server as a second toolset, so Basil can
    # build a cart the user reviews and checks out themselves. Leave these
    # blank and both the tools and the Instacart half of the system prompt
    # disappear — Basil never offers what it can't do.
    instacart_mcp_url: str = ""
    instacart_api_key: str = ""

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path}"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
