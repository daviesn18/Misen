"""Reminder preferences.

The notification itself is scheduled on the device (PRD §9). What lives here
is only the preference, so that a reinstall doesn't lose it and so Basil can
say "I'll nudge you Friday" and be telling the truth.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_default_is_off(client: TestClient, nick: dict[str, str]) -> None:
    assert client.get("/reminders", headers=nick).json() == {"day": None, "hour": None}


def test_set_a_reminder(client: TestClient, nick: dict[str, str]) -> None:
    """Friday or Saturday, to leave time to order groceries."""
    body = client.put("/reminders", headers=nick, json={"day": "friday", "hour": 17}).json()
    assert body == {"day": "friday", "hour": 17}
    assert client.get("/reminders", headers=nick).json() == body


def test_a_day_without_an_hour_gets_a_sensible_one(
    client: TestClient, nick: dict[str, str]
) -> None:
    body = client.put("/reminders", headers=nick, json={"day": "saturday"}).json()
    assert body == {"day": "saturday", "hour": 18}


def test_turning_it_off(client: TestClient, nick: dict[str, str]) -> None:
    client.put("/reminders", headers=nick, json={"day": "friday", "hour": 17})
    assert client.put("/reminders", headers=nick, json={"day": None}).json() == {
        "day": None,
        "hour": None,
    }


def test_an_hour_with_no_day_is_rejected(client: TestClient, nick: dict[str, str]) -> None:
    """A preference the server can't act on is how you get a reminder that
    never fires and nobody can explain why."""
    response = client.put("/reminders", headers=nick, json={"hour": 17})
    assert response.status_code == 400


def test_invalid_values_are_rejected(client: TestClient, nick: dict[str, str]) -> None:
    assert client.put("/reminders", headers=nick, json={"day": "funday"}).status_code == 422
    assert (
        client.put("/reminders", headers=nick, json={"day": "friday", "hour": 24}).status_code
        == 422
    )


def test_reminders_are_per_member_not_per_household(
    client: TestClient, auth: dict[str, dict[str, str]]
) -> None:
    client.put("/reminders", headers=auth["Nick"], json={"day": "friday", "hour": 17})
    assert client.get("/reminders", headers=auth["Mara"]).json() == {"day": None, "hour": None}
