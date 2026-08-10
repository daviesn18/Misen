"""Pantry endpoints, including the used/deleted distinction."""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient


def add(client: TestClient, headers: dict[str, str], **fields) -> dict:  # noqa: ANN003
    payload = {"name": "Salmon", "location": "fridge", **fields}
    response = client.post("/pantry", headers=headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_add_and_list(client: TestClient, nick: dict[str, str]) -> None:
    item = add(client, nick, name="Salmon", quantity="2 fillets", location="fridge")
    assert item["name"] == "Salmon"
    assert item["quantity"] == "2 fillets"
    assert item["used_at"] is None
    assert item["added_by"] is not None

    listed = client.get("/pantry", headers=nick).json()
    assert [i["name"] for i in listed] == ["Salmon"]


def test_location_filter(client: TestClient, nick: dict[str, str]) -> None:
    add(client, nick, name="Salmon", location="fridge")
    add(client, nick, name="Rice", location="pantry")

    fridge = client.get("/pantry?location=fridge", headers=nick).json()
    assert [i["name"] for i in fridge] == ["Salmon"]


def test_bad_location_is_rejected_readably(client: TestClient, nick: dict[str, str]) -> None:
    response = client.post(
        "/pantry", headers=nick, json={"name": "Salmon", "location": "garage"}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"


def test_marking_used_is_not_a_delete(client: TestClient, nick: dict[str, str]) -> None:
    """The whole point of `used_at`: the row survives so the history does."""
    item = add(client, nick, name="Salmon")

    updated = client.patch(f"/pantry/{item['id']}", headers=nick, json={"used": True}).json()
    assert updated["used_at"] is not None

    assert client.get("/pantry", headers=nick).json() == []

    including = client.get("/pantry?include_used=true", headers=nick).json()
    assert [i["name"] for i in including] == ["Salmon"]


def test_used_can_be_undone(client: TestClient, nick: dict[str, str]) -> None:
    item = add(client, nick)
    client.patch(f"/pantry/{item['id']}", headers=nick, json={"used": True})
    restored = client.patch(f"/pantry/{item['id']}", headers=nick, json={"used": False}).json()
    assert restored["used_at"] is None
    assert len(client.get("/pantry", headers=nick).json()) == 1


def test_delete_really_deletes(client: TestClient, nick: dict[str, str]) -> None:
    item = add(client, nick)
    assert client.delete(f"/pantry/{item['id']}", headers=nick).status_code == 204
    assert client.get("/pantry?include_used=true", headers=nick).json() == []


def test_partial_update_leaves_other_fields_alone(
    client: TestClient, nick: dict[str, str]
) -> None:
    """The bug this guards against: a client PATCHing one field and wiping the rest."""
    item = add(client, nick, name="Salmon", quantity="2 fillets", unit="fillet")

    updated = client.patch(
        f"/pantry/{item['id']}", headers=nick, json={"quantity": "1 fillet"}
    ).json()

    assert updated["quantity"] == "1 fillet"
    assert updated["name"] == "Salmon"
    assert updated["unit"] == "fillet"


def test_explicit_null_clears_a_field(client: TestClient, nick: dict[str, str]) -> None:
    item = add(client, nick, quantity="2 fillets")
    updated = client.patch(f"/pantry/{item['id']}", headers=nick, json={"quantity": None}).json()
    assert updated["quantity"] is None


def test_empty_patch_is_rejected(client: TestClient, nick: dict[str, str]) -> None:
    item = add(client, nick)
    response = client.patch(f"/pantry/{item['id']}", headers=nick, json={})
    assert response.status_code == 400


def test_missing_item_is_a_404(client: TestClient, nick: dict[str, str]) -> None:
    assert client.patch("/pantry/9999", headers=nick, json={"used": True}).status_code == 404
    assert client.delete("/pantry/9999", headers=nick).status_code == 404


def test_expiring_items_sort_first(client: TestClient, nick: dict[str, str]) -> None:
    """The reason to open the Pantry tab is to see what needs using."""
    today = date.today()
    add(client, nick, name="Rice", location="pantry")
    add(client, nick, name="Milk", location="fridge", expiry_date=str(today + timedelta(days=10)))
    add(client, nick, name="Salmon", location="fridge", expiry_date=str(today + timedelta(days=1)))

    names = [i["name"] for i in client.get("/pantry", headers=nick).json()]
    assert names == ["Salmon", "Milk", "Rice"]


def test_blank_name_is_rejected(client: TestClient, nick: dict[str, str]) -> None:
    response = client.post("/pantry", headers=nick, json={"name": "   ", "location": "fridge"})
    assert response.status_code == 422
