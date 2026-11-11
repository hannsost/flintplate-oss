from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.gastro.schemas import MenuPayload
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site
from tests.test_flintplate_nutrition import dish, guest_profile, seeded

pytest_plugins = ["tests.test_flintplate"]


async def order(client: AsyncClient, site: Site, *item_ids: str) -> dict:
    return body(
        await client.post(
            site.path("/orders"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "table_id": site.table_id,
                "lines": [{"item_id": item, "menu_version": 1, "quantity": 1} for item in item_ids],
            },
        ),
        201,
    )


async def ask(client: AsyncClient, site: Site, **payload: object) -> dict:
    return body(await client.post(site.path("/suggestions"), headers=site.headers, json=payload))


@pytest.mark.asyncio
async def test_items_that_travel_together_are_suggested(client: AsyncClient, site: Site) -> None:
    beer = await dish(client, site, "D-BIER", "Helles", contains=["alkohol", "gluten"])
    pretzel = await dish(client, site, "S-BREZ", "Brezel", contains=["gluten"])
    cake = await dish(client, site, "S-KUCH", "Kuchen", contains=["ei", "milch"])
    for _ in range(3):
        await order(client, site, beer["id"], pretzel["id"])
    await order(client, site, cake["id"])

    result = await ask(client, site, item_ids=[beer["id"]])

    assert result["basis"] == "gemeinsame Bestellungen"
    assert [row["name"] for row in result["suggestions"]] == ["Brezel"]
    top = result["suggestions"][0]
    assert top["together"] == 3 and top["of_orders"] == 3
    assert "3 von 3" in top["reason"]


@pytest.mark.asyncio
async def test_without_a_matching_history_the_popular_items_come_up(
    client: AsyncClient, site: Site
) -> None:
    soup = await dish(client, site, "S-SUPP", "Suppe")
    lonely = await dish(client, site, "S-EINZ", "Einzelgänger")
    for _ in range(2):
        await order(client, site, soup["id"])

    result = await ask(client, site, item_ids=[lonely["id"]])

    assert result["basis"] == "häufig bestellt"
    assert "Suppe" in [row["name"] for row in result["suggestions"]]
    assert "bestellt in den letzten" in result["suggestions"][0]["reason"]


@pytest.mark.asyncio
async def test_a_single_shared_order_is_not_enough(client: AsyncClient, site: Site) -> None:
    wine = await dish(client, site, "D-WEIN", "Wein")
    cheese = await dish(client, site, "S-KAES", "Käse")
    await order(client, site, wine["id"], cheese["id"])

    result = await ask(client, site, item_ids=[wine["id"]])

    # One order together is coincidence, not a pattern.
    assert result["basis"] == "häufig bestellt"


@pytest.mark.asyncio
async def test_suggestions_leave_out_what_the_guest_must_not_have(
    client: AsyncClient, site: Site
) -> None:
    await seeded(client, site)
    beer = await dish(client, site, "D-BIER", "Helles", contains=["alkohol"])
    pretzel = await dish(client, site, "S-BREZ", "Brezel", contains=["gluten"])
    for _ in range(3):
        await order(client, site, pretzel["id"], beer["id"])
    person = await guest_profile(client, site)
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

    plain = await ask(client, site, item_ids=[pretzel["id"]])
    assert "Helles" in [row["name"] for row in plain["suggestions"]]

    guarded = await ask(client, site, item_ids=[pretzel["id"]], profile_id=person["id"])
    assert "Helles" not in [row["name"] for row in guarded["suggestions"]]
    assert guarded["filtered_out"] == 1


@pytest.mark.asyncio
async def test_an_item_that_ran_out_stays_out_of_the_suggestions(
    client: AsyncClient, site: Site
) -> None:
    anchor = await dish(client, site, "S-ANKR", "Anker")
    gone = await dish(client, site, "S-WEG", "Ausverkauft")
    for _ in range(3):
        await order(client, site, anchor["id"], gone["id"])
    assert "Ausverkauft" in [
        row["name"] for row in (await ask(client, site, item_ids=[anchor["id"]]))["suggestions"]
    ]

    sold_out = MenuPayload(
        name="Ausverkauft", price_cents=900, tax_rate_bps=1900, cost_cents=200, available=False
    ).model_dump(mode="json")
    drafts = body(await client.get(site.path("/menu"), headers=site.headers))
    current = next(row for row in drafts if row["id"] == gone["id"])
    updated = body(
        await client.put(
            site.path(f"/menu/{gone['id']}"),
            headers=site.headers,
            json={"version": current["version"], "data": sold_out},
        )
    )
    body(
        await client.post(
            site.path(f"/menu/{gone['id']}/publish"),
            headers=site.headers,
            json={"version": updated["version"]},
        )
    )

    result = await ask(client, site, item_ids=[anchor["id"]])

    assert "Ausverkauft" not in [row["name"] for row in result["suggestions"]]


@pytest.mark.asyncio
async def test_the_guest_app_asks_for_itself(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    pretzel = await dish(client, site, "S-BREZ", "Brezel")
    lemonade = await dish(client, site, "D-LIMO", "Limonade")
    for _ in range(3):
        await order(client, site, pretzel["id"], lemonade["id"])
    body(await client.put(site.path("/guest-app"), headers=site.headers, json={"enabled": True}))
    guest = hr_workspace.headers("other_worker")

    result = body(
        await client.post(
            f"/guest/v1/{site.venue_id}/suggestions",
            headers=guest,
            json={"item_ids": [pretzel["id"]]},
        )
    )

    assert [row["name"] for row in result["suggestions"]] == ["Limonade"]


@pytest.mark.asyncio
async def test_multiple_anchors_count_the_union_of_matching_orders(
    client: AsyncClient, site: Site
) -> None:
    first = await dish(client, site, "ANCHOR-A", "Auswahl A")
    second = await dish(client, site, "ANCHOR-B", "Auswahl B")
    extra = await dish(client, site, "EXTRA-C", "Beilage C")
    for _ in range(2):
        await order(client, site, first["id"], extra["id"])
        await order(client, site, second["id"], extra["id"])
    await order(client, site, first["id"], second["id"])
    result = await ask(client, site, item_ids=[first["id"], second["id"]])
    suggestion = next(row for row in result["suggestions"] if row["item_id"] == extra["id"])
    assert suggestion["together"] == 4
    assert suggestion["of_orders"] == 5
    assert suggestion["share"] == 0.8
