from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.gastro.schemas import MenuPayload
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site

pytest_plugins = ["tests.test_flintplate"]


def test_recipe_allergen_labels_feed_existing_guest_exclusion_keys() -> None:
    data = MenuPayload(
        name="Curry",
        price_cents=900,
        tax_rate_bps=1900,
        ingredients=[{"name": "Erdnussmus", "allergens": ["Erdnüsse"]}],
    )
    assert data.allergens == ["Erdnüsse"]
    assert data.contains == ["erdnuss"]


async def dish(client: AsyncClient, site: Site, sku: str, name: str, **changes: object) -> dict:
    data = MenuPayload(
        name=name, price_cents=900, tax_rate_bps=1900, cost_cents=200, **changes
    ).model_dump(mode="json")
    item = body(
        await client.post(
            site.path("/menu"), headers=site.headers, json={"sku": sku, "data": data}
        ),
        201,
    )
    body(
        await client.post(
            site.path(f"/menu/{item['id']}/publish"), headers=site.headers, json={"version": 1}
        )
    )
    return item


async def seeded(client: AsyncClient, site: Site) -> dict[str, dict]:
    rows = body(await client.post(site.path("/diet-markers/defaults"), headers=site.headers), 201)
    return {row["key"]: row for row in rows}


async def guest_profile(client: AsyncClient, site: Site, **changes: object) -> dict:
    payload: dict[str, object] = {"display_name": "Gast Merkmal"}
    payload.update(changes)
    return body(await client.post(site.path("/guestbook"), headers=site.headers, json=payload), 201)


@pytest.mark.asyncio
async def test_defaults_are_seeded_once_and_carry_the_legal_block(
    client: AsyncClient, site: Site
) -> None:
    markers = await seeded(client, site)

    assert markers["minderjaehrig"]["legal_block"] is True
    assert markers["vegan"]["legal_block"] is False
    assert markers["halal"]["special"] is True
    assert "alkohol" in markers["minderjaehrig"]["avoid"]

    again = body(await client.post(site.path("/diet-markers/defaults"), headers=site.headers), 201)
    assert again == []


@pytest.mark.asyncio
async def test_the_ingredient_list_is_readable_for_the_service(
    client: AsyncClient, site: Site
) -> None:
    item = await dish(
        client,
        site,
        "S-CURRY",
        "Erdnusscurry",
        allergens=["Erdnüsse"],
        contains=["nuss", "erdnuss"],
        ingredients=[
            {"name": "Erdnussmus", "allergens": ["Erdnüsse"], "note": "geröstet"},
            {"name": "Kokosmilch", "allergens": []},
        ],
    )

    detail = body(await client.get(site.path(f"/menu/{item['id']}/details"), headers=site.headers))

    assert detail["name"] == "Erdnusscurry"
    assert [row["name"] for row in detail["ingredients"]] == ["Erdnussmus", "Kokosmilch"]
    assert detail["ingredients"][0]["note"] == "geröstet"
    assert detail["contains"] == ["erdnuss", "nuss"]
    assert detail["published"] is True


@pytest.mark.asyncio
async def test_the_public_snapshot_keeps_its_agreed_shape(client: AsyncClient, site: Site) -> None:
    await dish(
        client,
        site,
        "S-PUBLIC",
        "Hausbrot",
        contains=["gluten"],
        ingredients=[{"name": "Weizenmehl", "allergens": ["Gluten"]}],
    )
    body(await client.put(site.path("/guest-app"), headers=site.headers, json={"enabled": True}))

    public = body(await client.get(f"/guest/v1/{site.venue_id}/catalog"))

    entry = next(row for row in public if row["name"] == "Hausbrot")
    # FireFlint agreed on this shape; ingredients and cost stay internal.
    assert "ingredients" not in entry
    assert "contains" not in entry
    assert "cost_cents" not in entry


@pytest.mark.asyncio
async def test_a_check_separates_blocked_from_warned(client: AsyncClient, site: Site) -> None:
    markers = await seeded(client, site)
    beer = await dish(client, site, "D-BIER", "Helles", contains=["alkohol", "gluten"])
    salad = await dish(client, site, "S-SALAT", "Gartensalat", contains=[])
    cheese = await dish(client, site, "S-KAESE", "Käsespätzle", contains=["milch", "ei", "gluten"])

    result = body(
        await client.post(
            site.path("/menu-check"),
            headers=site.headers,
            json={
                "markers": ["minderjaehrig", "vegan"],
                "item_ids": [beer["id"], salad["id"], cheese["id"]],
            },
        )
    )

    verdicts = {row["item_id"]: row for row in result["verdicts"]}
    assert verdicts[beer["id"]]["state"] == "gesperrt"
    assert verdicts[cheese["id"]]["state"] == "warnung"
    assert verdicts[salad["id"]]["state"] == "ok"
    assert result["blocked"] == 1 and result["warned"] == 1
    assert "Minderjährig" in verdicts[beer["id"]]["reasons"][0]
    assert markers["vegan"]["key"] == "vegan"


@pytest.mark.asyncio
async def test_special_markers_need_the_same_consent_as_a_note(
    client: AsyncClient, site: Site
) -> None:
    await seeded(client, site)
    person = await guest_profile(client, site)

    refused = await client.put(
        site.path(f"/guestbook/{person['id']}/markers"),
        headers=site.headers,
        json={"version": person["version"], "markers": ["nussallergie"]},
    )
    assert refused.status_code == 409
    assert "Einwilligung" in refused.json()["detail"]

    plain = body(
        await client.put(
            site.path(f"/guestbook/{person['id']}/markers"),
            headers=site.headers,
            json={"version": person["version"], "markers": ["vegan"]},
        )
    )
    assert plain == ["vegan"]

    # The record has to carry them back, otherwise the interface cannot show them.
    detail = body(await client.get(site.path(f"/guestbook/{person['id']}"), headers=site.headers))
    assert detail["markers"] == ["vegan"]


@pytest.mark.asyncio
async def test_an_unknown_marker_is_refused(client: AsyncClient, site: Site) -> None:
    person = await guest_profile(client, site)

    response = await client.put(
        site.path(f"/guestbook/{person['id']}/markers"),
        headers=site.headers,
        json={"version": person["version"], "markers": ["fantasiediaet"]},
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_venue_adds_its_own_diet(client: AsyncClient, site: Site) -> None:
    created = body(
        await client.post(
            site.path("/diet-markers"),
            headers=site.headers,
            json={
                "key": "pescetarisch",
                "label": "Pescetarisch",
                "kind": "diaet",
                "avoid": ["Fleisch", "fleisch "],
            },
        ),
        201,
    )
    assert created["avoid"] == ["fleisch"]

    steak = await dish(client, site, "S-STEAK", "Rumpsteak", contains=["fleisch"])
    result = body(
        await client.post(
            site.path("/menu-check"),
            headers=site.headers,
            json={"markers": ["pescetarisch"], "item_ids": [steak["id"]]},
        )
    )

    assert result["verdicts"][0]["state"] == "warnung"
    assert "Pescetarisch" in result["verdicts"][0]["reasons"][0]


@pytest.mark.asyncio
async def test_the_guest_app_blocks_alcohol_for_a_minor(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    await seeded(client, site)
    beer = await dish(client, site, "D-BIER", "Helles", contains=["alkohol"])
    body(await client.put(site.path("/guest-app"), headers=site.headers, json={"enabled": True}))
    guest = hr_workspace.headers("other_worker")
    base = f"/guest/v1/{site.venue_id}"
    body(
        await client.post(
            base + "/orders",
            headers=guest,
            json={
                "request_key": str(uuid.uuid4()),
                "table_id": None,
                "fulfillment": "takeaway",
                "lines": [{"item_id": site.item_id, "menu_version": 1, "quantity": 1}],
            },
        ),
        201,
    )
    account = body(await client.get(base + "/account", headers=guest))
    person = await guest_profile(client, site, account_id=account["id"])
    body(
        await client.put(
            site.path(f"/guestbook/{person['id']}/consent"),
            headers=site.headers,
            json={"version": person["version"], "granted": True},
        )
    )
    body(
        await client.put(
            site.path(f"/guestbook/{person['id']}/markers"),
            headers=site.headers,
            json={"version": person["version"] + 1, "markers": ["minderjaehrig"]},
        )
    )

    blocked = await client.post(
        base + "/orders",
        headers=guest,
        json={
            "request_key": str(uuid.uuid4()),
            "table_id": None,
            "fulfillment": "takeaway",
            "lines": [{"item_id": beer["id"], "menu_version": 1, "quantity": 1}],
            "accept_warnings": True,
        },
    )

    assert blocked.status_code == 409
    assert "Nicht möglich" in blocked.json()["detail"]


@pytest.mark.asyncio
async def test_a_warning_can_be_confirmed_by_the_guest(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    await seeded(client, site)
    cheese = await dish(client, site, "S-KAESE", "Käsespätzle", contains=["milch"])
    body(await client.put(site.path("/guest-app"), headers=site.headers, json={"enabled": True}))
    guest = hr_workspace.headers("other_worker")
    base = f"/guest/v1/{site.venue_id}"
    body(
        await client.post(
            base + "/orders",
            headers=guest,
            json={
                "request_key": str(uuid.uuid4()),
                "table_id": None,
                "fulfillment": "takeaway",
                "lines": [{"item_id": site.item_id, "menu_version": 1, "quantity": 1}],
            },
        ),
        201,
    )
    account = body(await client.get(base + "/account", headers=guest))
    person = await guest_profile(client, site, account_id=account["id"])
    body(
        await client.put(
            site.path(f"/guestbook/{person['id']}/markers"),
            headers=site.headers,
            json={"version": person["version"], "markers": ["vegan"]},
        )
    )
    order = {
        "request_key": str(uuid.uuid4()),
        "table_id": None,
        "fulfillment": "takeaway",
        "lines": [{"item_id": cheese["id"], "menu_version": 1, "quantity": 1}],
    }

    warned = await client.post(base + "/orders", headers=guest, json=order)
    assert warned.status_code == 409
    assert "Bitte bestätigen" in warned.json()["detail"]

    confirmed = await client.post(
        base + "/orders",
        headers=guest,
        json={**order, "request_key": str(uuid.uuid4()), "accept_warnings": True},
    )
    assert confirmed.status_code == 201
