from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from tests.hr_support import body
from tests.test_flintplate import Site

pytest_plugins = ["tests.test_flintplate"]


def window(minutes: int = 90, days: int = 9) -> tuple[str, str]:
    start = (datetime.now(UTC) + timedelta(days=days)).replace(
        hour=18, minute=0, second=0, microsecond=0
    )
    return start.isoformat(), (start + timedelta(minutes=minutes)).isoformat()


async def add_table(
    client: AsyncClient, site: Site, name: str, seats: int, **extra: object
) -> dict:
    return body(
        await client.post(
            site.path("/tables"),
            headers=site.headers,
            json={"name": name, "seats": seats, **extra},
        ),
        201,
    )


async def link(
    client: AsyncClient, site: Site, table: dict, partners: list[str], **extra: object
) -> dict:
    """The resource PUT replaces the whole record, so unchanged fields travel with it."""
    return body(
        await client.put(
            site.path(f"/tables/{table['id']}"),
            headers=site.headers,
            json={
                "name": table["name"],
                "seats": table["seats"],
                "version": table["version"],
                "combinable_with": partners,
                **extra,
            },
        )
    )


async def propose(client: AsyncClient, site: Site, **changes: object) -> dict:
    starts_at, ends_at = window()
    payload: dict[str, object] = {"starts_at": starts_at, "ends_at": ends_at, "guests": 2}
    payload.update(changes)
    return body(
        await client.post(site.path("/reservations/propose"), headers=site.headers, json=payload)
    )


async def reserve(client: AsyncClient, site: Site, table_id: str, guests: int = 2) -> dict:
    starts_at, ends_at = window()
    return body(
        await client.post(
            site.path("/reservations"),
            headers=site.headers,
            json={
                "table_id": table_id,
                "guest_name": "Blockierer",
                "guests": guests,
                "starts_at": starts_at,
                "ends_at": ends_at,
            },
        ),
        201,
    )


@pytest.mark.asyncio
async def test_proposal_offers_three_distinct_resources(client: AsyncClient, site: Site) -> None:
    await add_table(client, site, "T02", 2)
    await add_table(client, site, "T06", 6)
    await add_table(client, site, "T08", 8)

    result = await propose(client, site)

    assert len(result["options"]) == 3
    keys = [option["key"] for option in result["options"]]
    assert keys == ["best_fit", "keep_open", "preference"]
    chosen = [tuple(option["table_ids"]) for option in result["options"]]
    assert len(set(chosen)) == 3
    for option in result["options"]:
        assert option["seats"] >= 2
        assert option["reasons"]
    assert result["engine"] == "rules"


@pytest.mark.asyncio
async def test_every_option_states_what_it_optimises_for(client: AsyncClient, site: Site) -> None:
    await add_table(client, site, "T02", 2)
    await add_table(client, site, "T06", 6)

    result = await propose(client, site)

    leads = [option["reasons"][0] for option in result["options"]]
    assert len(set(leads)) == len(leads)
    assert any("passgenaueste" in lead for lead in leads)
    assert any("Nachbarn" in lead for lead in leads)
    assert any("gepflegt" in note for note in result["notes"])


@pytest.mark.asyncio
async def test_occupied_and_undersized_resources_never_appear(
    client: AsyncClient, site: Site
) -> None:
    small = await add_table(client, site, "T02", 2)
    large = await add_table(client, site, "T10", 10, min_party=6)
    blocked = await add_table(client, site, "T04", 4)
    await reserve(client, site, blocked["id"])

    result = await propose(client, site, guests=2)

    offered = {table_id for option in result["options"] for table_id in option["table_ids"]}
    assert small["id"] in offered
    assert blocked["id"] not in offered
    assert large["id"] not in offered


@pytest.mark.asyncio
async def test_keep_open_option_protects_a_combinable_pair(client: AsyncClient, site: Site) -> None:
    first = await add_table(client, site, "A01", 4)
    second = await add_table(client, site, "B01", 4)
    await link(client, site, first, [second["id"]])
    await link(client, site, second, [first["id"]])
    await add_table(client, site, "Z01", 4)

    result = await propose(client, site, guests=4)

    option = next(row for row in result["options"] if row["key"] == "keep_open")
    assert not {first["id"], second["id"]} & set(option["table_ids"])
    assert any("Nachbartische" in reason for reason in option["reasons"])


@pytest.mark.asyncio
async def test_large_party_gets_a_combination(client: AsyncClient, site: Site) -> None:
    first = await add_table(client, site, "A01", 4)
    second = await add_table(client, site, "B01", 4)
    await link(client, site, first, [second["id"]])
    await link(client, site, second, [first["id"]])

    result = await propose(client, site, guests=7)

    option = result["options"][0]
    assert len(option["table_ids"]) == 2
    assert option["seats"] == 8
    assert any("Zusammengestellt" in reason for reason in option["reasons"])


@pytest.mark.asyncio
async def test_combination_respects_the_strictest_minimum_group_size(
    client: AsyncClient, site: Site
) -> None:
    first = await add_table(client, site, "A01", 8, min_party=8)
    second = await add_table(client, site, "B01", 4)
    await link(client, site, first, [second["id"]], min_party=8, seats=8)

    result = await propose(client, site, guests=5)

    assert result["options"] == []
    assert any("keine Ressource" in note for note in result["notes"])


@pytest.mark.asyncio
async def test_full_window_offers_other_times_instead_of_a_refusal(
    client: AsyncClient, site: Site
) -> None:
    extra = await add_table(client, site, "T02", 2)
    tables = body(await client.get(site.path("/tables"), headers=site.headers))
    starts_at, ends_at = window(minutes=30)
    for table in tables:
        body(
            await client.post(
                site.path("/reservations"),
                headers=site.headers,
                json={
                    "table_id": table["id"],
                    "guest_name": "Blockierer",
                    "guests": 2,
                    "starts_at": starts_at,
                    "ends_at": ends_at,
                },
            ),
            201,
        )

    result = body(
        await client.post(
            site.path("/reservations/propose"),
            headers=site.headers,
            json={"starts_at": starts_at, "ends_at": ends_at, "guests": 2},
        )
    )

    assert extra["id"] in {table["id"] for table in tables}
    assert result["options"]
    assert all(option["key"].startswith("shift_") for option in result["options"])
    assert all(option["starts_at"] != starts_at for option in result["options"])
    assert any("verschieben" in note for note in result["notes"])


@pytest.mark.asyncio
async def test_accepting_books_the_option_once_and_records_the_choice(
    client: AsyncClient, site: Site
) -> None:
    await add_table(client, site, "T06", 6)
    result = await propose(client, site, guests=4)
    option = result["options"][0]

    created = body(
        await client.post(
            site.path(f"/decisions/{result['decision_id']}/accept"),
            headers=site.headers,
            json={"version": 1, "option_key": option["key"], "guest_name": "Familie Funke"},
        ),
        201,
    )
    assert len(created) == len(option["table_ids"])

    reservations = body(await client.get(site.path("/reservations"), headers=site.headers))
    assert {row["id"] for row in reservations} >= set(created)

    history = body(await client.get(site.path("/decisions"), headers=site.headers))
    recorded = next(row for row in history if row["id"] == result["decision_id"])
    assert recorded["chosen_key"] == option["key"]
    assert recorded["chosen_at"]

    again = await client.post(
        site.path(f"/decisions/{result['decision_id']}/accept"),
        headers=site.headers,
        json={"version": 2, "option_key": option["key"], "guest_name": "Familie Funke"},
    )
    assert again.status_code == 409


@pytest.mark.asyncio
async def test_accepting_rechecks_a_meanwhile_taken_resource(
    client: AsyncClient, site: Site
) -> None:
    await add_table(client, site, "T06", 6)
    result = await propose(client, site, guests=4)
    option = result["options"][0]
    await reserve(client, site, option["table_ids"][0], guests=4)

    response = await client.post(
        site.path(f"/decisions/{result['decision_id']}/accept"),
        headers=site.headers,
        json={"version": 1, "option_key": option["key"], "guest_name": "Zu spät"},
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_prompt_is_recorded_and_declared_unapplied_without_a_model(
    client: AsyncClient, site: Site
) -> None:
    result = await propose(client, site, prompt="Bitte den ruhigsten Platz am Fenster.")

    assert result["prompt_applied"] is False
    assert result["engine"] == "rules"
    assert "regelbasiert" in result["prompt_note"]

    history = body(await client.get(site.path("/decisions"), headers=site.headers))
    recorded = next(row for row in history if row["id"] == result["decision_id"])
    assert "ruhigsten Platz" in recorded["prompt"]
    assert recorded["prompt_applied"] is False


@pytest.mark.asyncio
async def test_saved_criteria_join_every_later_proposal(client: AsyncClient, site: Site) -> None:
    body(
        await client.post(
            site.path("/decision-criteria"),
            headers=site.headers,
            json={"label": "Stammgäste", "text": "Stammgäste sitzen bevorzugt am Fenster."},
        ),
        201,
    )
    duplicate = await client.post(
        site.path("/decision-criteria"),
        headers=site.headers,
        json={"label": "Stammgäste", "text": "Andere Formulierung."},
    )
    assert duplicate.status_code == 409

    result = await propose(client, site)

    assert any("gespeicherte Kriterien" in note for note in result["notes"])
    history = body(await client.get(site.path("/decisions"), headers=site.headers))
    recorded = next(row for row in history if row["id"] == result["decision_id"])
    assert "Stammgäste sitzen bevorzugt" in recorded["prompt"]


@pytest.mark.asyncio
async def test_combinable_partner_must_belong_to_the_venue(client: AsyncClient, site: Site) -> None:
    table = body(await client.get(site.path("/tables"), headers=site.headers))[0]

    response = await client.put(
        site.path(f"/tables/{table['id']}"),
        headers=site.headers,
        json={
            "name": table["name"],
            "seats": table["seats"],
            "version": table["version"],
            "combinable_with": [table["id"]],
        },
    )

    assert response.status_code == 422
