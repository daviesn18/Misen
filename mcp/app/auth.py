"""Bearer auth, delegated to Companion.

**This server is stateless and holds no member credentials.** The token a
caller presents is the member's own Companion token; verification is a `GET
/me` against Companion, and every subsequent tool call forwards that same
token. The MCP server can therefore reach exactly what the caller could reach
and nothing more.

That is a deliberate simplification of PRD §10, which described the MCP server
as holding "its own bearer token per member". A second token per member would
mean a second secret store, a second rotation path, and a second thing to get
out of sync — for identical blast radius, since the tool surface covers most of
the API anyway.

The practical consequence worth stating plainly: the member pastes that token
into claude.ai when adding this server as a connector, so claude.ai's servers
can call this one. Rotation is `provision.py --rotate`, and it invalidates the
app and the connector at once, which is the upside of there being only one
credential to rotate.

Static bearer tokens are what this accepts today. OAuth — so a member signs in
rather than pasting a token — is the next piece of work, and the property to
preserve when it lands is the one above: this server verifies with Companion
and forwards, and stores nothing itself.
"""

from __future__ import annotations

import logging

from fastmcp.server.auth import TokenVerifier
from mcp.server.auth.provider import AccessToken

from app.clients import companion

logger = logging.getLogger(__name__)


class CompanionTokenVerifier(TokenVerifier):
    """Verifies a member token by asking Companion who it belongs to."""

    async def verify_token(self, token: str) -> AccessToken | None:
        member = await companion().me(token)
        if member is None:
            return None

        # `token` is carried through so tools can forward it. `claims` holds the
        # member so a tool can answer "who am I" without a second round trip.
        return AccessToken(
            token=token,
            client_id=str(member.get("id", "")),
            scopes=[],
            subject=str(member.get("id", "")),
            claims=member,
        )
