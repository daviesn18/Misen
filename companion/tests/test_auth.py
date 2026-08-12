"""Auth and capability gating."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import generate_token, hash_token

PROTECTED = [
    ("get", "/me"),
    ("get", "/household"),
    ("get", "/pantry"),
    ("get", "/menu"),
    ("get", "/shopping"),
    ("get", "/reminders"),
    ("get", "/recipes/roast-chicken/scaled"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_every_endpoint_requires_a_token(
    client: TestClient, households: dict, method: str, path: str
) -> None:
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize(
    "header",
    [
        {"Authorization": "Bearer "},
        {"Authorization": "Basic abc123"},
        {"Authorization": "abc123"},
        {"Authorization": f"Bearer {generate_token()}"},  # well-formed, unknown
    ],
)
def test_bad_tokens_are_rejected(
    client: TestClient, households: dict, header: dict[str, str]
) -> None:
    response = client.get("/me", headers=header)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_health_needs_no_token(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


def test_me_returns_the_calling_member(
    client: TestClient, nick: dict[str, str]
) -> None:
    body = client.get("/me", headers=nick).json()
    assert body["name"] == "Nick"
    assert body["role"] == "adult"


def test_a_child_has_the_same_access_as_an_adult(
    client: TestClient, auth: dict[str, dict[str, str]]
) -> None:
    """`role` records who someone is, not what they may do.

    It exists for display and for `cooked_by`; nothing in the API branches on
    it. Ivy can see and plan dinner exactly as her parents can.
    """
    body = client.get("/me", headers=auth["Ivy"]).json()
    assert body["role"] == "child"
    assert client.get("/pantry", headers=auth["Ivy"]).status_code == 200
    assert client.get("/menu", headers=auth["Ivy"]).status_code == 200


def test_tokens_are_never_stored_in_the_clear(
    client: TestClient, households: dict, db
) -> None:  # noqa: ANN001
    from app.models import Member

    token = households["first"]["tokens"]["Nick"]
    stored = {m.token_hash for m in db.query(Member).all()}
    assert token not in stored
    assert hash_token(token) in stored


def test_error_bodies_use_the_one_envelope(client: TestClient, households: dict) -> None:
    body = client.get("/me").json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message"}
    # The message is shown to a person, so it must read like one.
    assert body["error"]["message"][0].isupper()


def test_unknown_paths_use_the_envelope_too(client: TestClient) -> None:
    body = client.get("/nope").json()
    assert "error" in body and "code" in body["error"]
