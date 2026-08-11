"""Uvicorn entrypoint.

    uvicorn app.main:app --host 0.0.0.0 --port 8001

The MCP endpoint is at /mcp. Caddy fronts this at https://mcp.misen.<domain>,
which is the URL Companion hands to Anthropic in `mcp_servers[].url` — so it
has to be reachable from the public internet, not just from the house.
"""

from __future__ import annotations

from app.server import build_app

app = build_app()
