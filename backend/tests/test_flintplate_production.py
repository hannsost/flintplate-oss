from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient

from tests.hr_support import body
from tests.test_flintplate import Site, sent_order

pytest_plugins = ["tests.test_flintplate"]


@pytest.mark.asyncio
async def test_subrecipe_inherits_allergens_cost_and_consumes_only_its_frozen_batch(
    client: AsyncClient, site: Site
) -> None:
    setup = await setup_recipe(client, site)

    async def post(path: str, data: dict) -> dict:
        return body(await client.post(site.path(path), headers=site.headers, json=data), 201)

    async def prep(recipe: dict, code: str, days: int) -> dict:
        return await post(
            "/prep",
            {
                "request_key": str(uuid.uuid4()),
                "reason": "Versionierte Unterrezeptproduktion",
                "recipe_id": recipe["id"],
                "batches": "1",
                "output_quantity": "10",
                "location_id": setup["location"]["id"],
                "owner_id": setup["owner"]["id"],
                "lot_code": code,
                "expires_on": (date.today() + timedelta(days=days)).isoformat(),
            },
        )

    await prep(setup["recipe"], "PASTA-GLUTEN", 5)
    output = await post(
        "/inventory/items", {"sku": "PLATE", "name": "Pastateller", "unit": "piece"}
    )
    parent_data = {
        "request_key": str(uuid.uuid4()),
        "name": "Pastateller aus geprüftem Prep",
        "menu_item_id": site.item_id,
        "menu_version": setup["recipe"]["menu_version"],
        "output_item_id": output["id"],
        "yield_quantity": "1",
        "allergen_reviewed": True,
        "components": [
            {
                "stock_item_id": setup["output"]["id"],
                "quantity": "2",
                "unit_cost_cents": setup["recipe"]["cost_cents"],
                "subrecipe_id": setup["recipe"]["id"],
            }
        ],
    }
    parent = await post("/recipes", parent_data)
    assert parent["cost_cents"] == 100 and parent["allergens"] == ["gluten"]
    assert parent["components"][0]["subrecipe_id"] == setup["recipe"]["id"]
    body(
        await client.post(
            site.path(f"/menu/{site.item_id}/publish"),
            headers=site.headers,
            json={"version": parent["menu_version"]},
        )
    )
    other_version = await post(
        "/recipes",
        {
            "request_key": str(uuid.uuid4()),
            "name": "Neue Variante mit Milch",
            "output_item_id": setup["output"]["id"],
            "yield_quantity": "10",
            "allergen_reviewed": True,
            "components": [
                {
                    "stock_item_id": setup["flour"]["id"],
                    "quantity": "2.5",
                    "unit_cost_cents": 200,
                    "allergens": ["milch"],
                }
            ],
        },
    )
    await prep(other_version, "PASTA-MILCH", 1)
    order = await sent_order(
        client,
        site,
        lines=[{"item_id": site.item_id, "menu_version": parent["menu_version"], "quantity": 1}],
    )
    body(
        await client.post(
            site.path(f"/orders/{order['id']}/status"),
            headers=site.headers,
            json={"version": order["version"], "status": "preparing"},
        )
    )
    stock = body(await client.get(site.path("/inventory/snapshot"), headers=site.headers))
    by_code = {lot["id"]: lot["code"] for lot in stock["lots"]}
    quantity = {by_code[row["lot_id"]]: float(row["quantity"]) for row in stock["balances"]}
    assert quantity["PASTA-GLUTEN"] == 8 and quantity["PASTA-MILCH"] == 10
    provenance = body(
        await client.get(site.path(f"/orders/{order['id']}/provenance"), headers=site.headers)
    )
    assert {lot["code"] for lot in provenance["lots"]} == {"F001", "PASTA-GLUTEN"}
    assert (await post("/recipes", parent_data))["id"] == parent["id"]


def test_optional_subrecipe_preserves_legacy_recipe_request_serialization() -> None:
    from app.gastro.recipes import Component

    component = Component(stock_item_id=uuid.uuid4(), quantity="1", unit_cost_cents=100)
    assert "subrecipe_id" not in component.model_dump(mode="json")


@pytest.mark.asyncio
async def test_recipe_cannot_take_over_partner_sale_article(
    client: AsyncClient, site: Site
) -> None:
    from tests.test_flintplate_partners import setup_partner

    setup = await setup_partner(client, site)
    output = body(
        await client.post(
            site.path("/inventory/items"),
            headers=site.headers,
            json={"sku": "OWN-OUTPUT", "name": "Eigenes Gericht", "unit": "piece"},
        ),
        201,
    )
    response = await client.post(
        site.path("/recipes"),
        headers=site.headers,
        json={
            "request_key": str(uuid.uuid4()),
            "name": "Widerspruch zur Partnerware",
            "menu_item_id": site.item_id,
            "menu_version": 1,
            "output_item_id": output["id"],
            "yield_quantity": "1",
            "allergen_reviewed": True,
            "components": [
                {"stock_item_id": setup["item_id"], "quantity": "1", "unit_cost_cents": 100}
            ],
        },
    )
    assert response.status_code == 409 and "Partnervertrag" in response.json()["detail"]


async def setup_recipe(client: AsyncClient, site: Site) -> dict:
    async def post(path: str, data: dict) -> dict:
        return body(await client.post(site.path(path), headers=site.headers, json=data), 201)

    owner = await post("/inventory/owners", {"name": "Eigener Betrieb", "kind": "own"})
    location = await post("/inventory/locations", {"name": "Trockenlager"})
    flour = await post("/inventory/items", {"sku": "FLOUR", "name": "Mehl", "unit": "kg"})
    output = await post(
        "/inventory/items", {"sku": "PASTA", "name": "Pasta-Portion", "unit": "piece"}
    )
    receipt = await post(
        "/inventory/receipts",
        {
            "request_key": str(uuid.uuid4()),
            "reason": "Einkauf Testlieferung",
            "item_id": flour["id"],
            "owner_id": owner["id"],
            "location_id": location["id"],
            "lot_code": "F001",
            "quantity": "10",
            "reference": "Testlieferung",
        },
    )
    recipe = await post(
        "/recipes",
        {
            "request_key": str(uuid.uuid4()),
            "name": "Pasta",
            "menu_item_id": site.item_id,
            "menu_version": 1,
            "output_item_id": output["id"],
            "yield_quantity": "10",
            "components": [
                {
                    "stock_item_id": flour["id"],
                    "quantity": "2.5",
                    "unit_cost_cents": 200,
                    "allergens": ["gluten"],
                }
            ],
            "allergen_reviewed": True,
        },
    )
    body(
        await client.post(
            site.path(f"/menu/{site.item_id}/publish"),
            headers=site.headers,
            json={"version": recipe["menu_version"]},
        )
    )
    return {
        "owner": owner,
        "location": location,
        "flour": flour,
        "output": output,
        "recipe": recipe,
        "receipt": receipt,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("output_unit", ["kg", "l"])
async def test_sale_recipe_requires_portions_but_internal_bulk_recipe_remains_valid(
    client: AsyncClient, site: Site, output_unit: str
) -> None:
    async def post(path: str, data: dict) -> dict:
        return body(await client.post(site.path(path), headers=site.headers, json=data), 201)

    ingredient = await post("/inventory/items", {"sku": "BULK-RAW", "name": "Zutat", "unit": "kg"})
    output = await post(
        "/inventory/items", {"sku": "BULK-PREP", "name": "Saucenbasis", "unit": output_unit}
    )
    data = {
        "request_key": str(uuid.uuid4()),
        "name": "Saucenbasis",
        "menu_item_id": site.item_id,
        "menu_version": 1,
        "output_item_id": output["id"],
        "yield_quantity": "5",
        "components": [
            {"stock_item_id": ingredient["id"], "quantity": "1", "unit_cost_cents": 500}
        ],
        "allergen_reviewed": True,
    }
    rejected = await client.post(site.path("/recipes"), headers=site.headers, json=data)
    assert rejected.status_code == 422 and "Portionen" in rejected.json()["detail"]
    # A rejected binding changes neither the card version nor its cost snapshot.
    menu = body(await client.get(site.path("/menu"), headers=site.headers))
    card = next(item for item in menu if item["id"] == site.item_id)
    assert card["version"] == 1
    internal = await post("/recipes", {**data, "menu_item_id": None, "menu_version": None})
    assert internal["menu_item_id"] is None and internal["cost_cents"] == 100


@pytest.mark.asyncio
async def test_recipe_cost_allergens_and_order_consumption_once(
    client: AsyncClient, site: Site
) -> None:
    setup = await setup_recipe(client, site)
    recipe = setup["recipe"]
    assert recipe["cost_cents"] == 50
    order = await sent_order(
        client,
        site,
        lines=[{"item_id": site.item_id, "menu_version": recipe["menu_version"], "quantity": 2}],
    )
    assert order["lines"][0]["recipe_id"] == recipe["id"]
    assert order["lines"][0]["allergens"] == ["gluten"]
    data = {"request_key": str(uuid.uuid4()), "version": order["version"], "status": "preparing"}
    for _ in range(2):
        body(
            await client.post(
                site.path(f"/orders/{order['id']}/lines/{order['lines'][0]['line_id']}/status"),
                headers=site.headers,
                json=data,
            )
        )
    snapshot = body(await client.get(site.path("/inventory/snapshot"), headers=site.headers))
    assert float(snapshot["balances"][0]["quantity"]) == 9.5


@pytest.mark.asyncio
async def test_prep_has_immutable_input_output_trace_and_replay(
    client: AsyncClient, site: Site
) -> None:
    setup = await setup_recipe(client, site)
    payload = {
        "request_key": str(uuid.uuid4()),
        "reason": "Mise en place",
        "recipe_id": setup["recipe"]["id"],
        "batches": "1",
        "output_quantity": "9",
        "owner_id": setup["owner"]["id"],
        "location_id": setup["location"]["id"],
        "lot_code": "PREP001",
        "expires_on": (date.today() + timedelta(days=2)).isoformat(),
    }
    first = body(await client.post(site.path("/prep"), headers=site.headers, json=payload), 201)
    again = body(await client.post(site.path("/prep"), headers=site.headers, json=payload), 201)
    assert first["id"] == again["id"]
    history = body(await client.get(site.path("/inventory/operations"), headers=site.headers))
    production = next(op for op in history if op["id"] == first["operation_id"])
    assert sorted(float(move["quantity"]) for move in production["movements"]) == [-2.5, 9.0]


@pytest.mark.asyncio
async def test_haccp_requires_action_and_retains_correction_chain(
    client: AsyncClient, site: Site
) -> None:
    data = {
        "request_key": str(uuid.uuid4()),
        "name": "Kühlkontrolle",
        "location": "Kühlhaus",
        "value": "9",
        "minimum": "1",
        "maximum": "7",
        "unit": "°C",
    }
    assert (
        await client.post(site.path("/haccp"), headers=site.headers, json=data)
    ).status_code == 422
    failed = body(
        await client.post(
            site.path("/haccp"),
            headers=site.headers,
            json={**data, "correction": "Ware gesperrt und Kühlung geprüft"},
        ),
        201,
    )
    good = body(
        await client.post(
            site.path("/haccp"),
            headers=site.headers,
            json={
                **data,
                "request_key": str(uuid.uuid4()),
                "corrects_id": failed["id"],
                "value": "4",
            },
        ),
        201,
    )
    assert failed["result"] == "deviation" and good["result"] == "ok"
    rows = body(await client.get(site.path("/haccp"), headers=site.headers))
    assert len(rows) == 2 and rows[0]["corrects_id"] == failed["id"]


@pytest.mark.asyncio
async def test_recall_blocks_source_and_derived_prep_lots(client: AsyncClient, site: Site) -> None:
    setup = await setup_recipe(client, site)
    prep = body(
        await client.post(
            site.path("/prep"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "reason": "Mise en place",
                "recipe_id": setup["recipe"]["id"],
                "batches": "1",
                "output_quantity": "10",
                "owner_id": setup["owner"]["id"],
                "location_id": setup["location"]["id"],
                "lot_code": "RECALL-PREP",
                "expires_on": (date.today() + timedelta(days=2)).isoformat(),
            },
        ),
        201,
    )
    source_id = setup["receipt"]["movements"][0]["lot_id"]
    data = {
        "request_key": str(uuid.uuid4()),
        "reason": "Lieferantenrückruf wegen Qualitätsabweichung",
    }
    for _ in range(2):
        traced = body(
            await client.post(
                site.path(f"/inventory/lots/{source_id}/recall"), headers=site.headers, json=data
            )
        )
        assert set(traced["affected_lot_ids"]) == {source_id, prep["output_lot_id"]}
    snapshot = body(await client.get(site.path("/inventory/snapshot"), headers=site.headers))
    assert all(lot["blocked"] for lot in snapshot["lots"])


def test_displayed_ingredient_allergens_also_feed_dietary_checks() -> None:
    from app.gastro.schemas import MenuPayload

    payload = MenuPayload(
        name="Käsesuppe",
        price_cents=1000,
        tax_rate_bps=1900,
        ingredients=[{"name": "Käse", "allergens": ["milch"]}],
    )
    assert payload.allergens == ["milch"]
    assert "milch" in payload.contains


@pytest.mark.asyncio
async def test_price_edit_keeps_recipe_and_allergen_edits_require_revision(
    client: AsyncClient, site: Site
) -> None:
    setup = await setup_recipe(client, site)
    rows = body(await client.get(site.path("/menu"), headers=site.headers))
    item = next(row for row in rows if row["id"] == site.item_id)
    updated = body(
        await client.put(
            site.path(f"/menu/{site.item_id}"),
            headers=site.headers,
            json={"version": item["version"], "data": {**item["draft"], "price_cents": 1200}},
        )
    )
    body(
        await client.post(
            site.path(f"/menu/{site.item_id}/publish"),
            headers=site.headers,
            json={"version": updated["version"]},
        )
    )
    order = await sent_order(
        client,
        site,
        lines=[{"item_id": site.item_id, "menu_version": updated["version"], "quantity": 1}],
    )
    assert order["lines"][0]["recipe_id"] == setup["recipe"]["id"]
    assert (
        await client.put(
            site.path(f"/menu/{site.item_id}"),
            headers=site.headers,
            json={
                "version": updated["version"],
                "data": {**updated["draft"], "ingredients": [], "allergens": [], "contains": []},
            },
        )
    ).status_code == 409
