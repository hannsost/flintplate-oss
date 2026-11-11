"""Delivery promises are versioned evidence, never physical stock."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.purchasing_math import request_digest
from app.gastro.purchasing_schemas import PurchaseReceiptInput
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site
from tests.test_flintplate_purchasing import catalog, delivered, delivery_input, ordered

pytest_plugins = ["tests.test_flintplate"]


def promise(order: dict, **changes: object) -> dict:
    return {
        "request_key": str(uuid.uuid4()),
        "line_id": order["lines"][0]["id"],
        "expected_version": 0,
        "status": "confirmed",
        "expected_on": (date.today() + timedelta(days=2)).isoformat(),
        "paid_quantity": "3",
        "bonus_quantity": "0",
        "reference": "AB-123",
        "reason": "Schriftliche Zusage erfasst",
        **changes,
    }


async def latest(client: AsyncClient, site: Site, line_id: str) -> dict:
    return body(
        await client.get(
            site.path("/purchasing/delivery-confirmations"),
            params={"line_id": line_id},
            headers=site.headers,
        )
    )[0]


@pytest.mark.asyncio
async def test_partial_arrival_replacement_and_old_retry_preserve_exact_promise(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    order = await ordered(client, site, setup)
    payload = promise(order)
    url = site.path("/purchasing/delivery-confirmations")
    first = body(await client.post(url, headers=site.headers, json=payload), 201)
    assert first["reliable_for_planning"] and Decimal(first["remaining_physical_quantity"]) == 3
    delivery = delivery_input(setup, order, accepted_quantity="1", confirmation_id=first["id"])
    receive_url = site.path(f"/purchasing/orders/{order['id']}/receipts")
    body(await client.post(receive_url, headers=site.headers, json=delivery), 201)
    assert Decimal((await latest(client, site, payload["line_id"]))["remaining_paid_quantity"]) == 2
    replacement = body(
        await client.post(
            url,
            headers=site.headers,
            json=promise(
                order,
                expected_version=1,
                paid_quantity="4",
                expected_on=(date.today() + timedelta(days=4)).isoformat(),
            ),
        ),
        201,
    )
    assert replacement["version"] == 2 and Decimal(replacement["remaining_physical_quantity"]) == 4
    replay = body(await client.post(url, headers=site.headers, json=payload), 201)
    assert replay["id"] == first["id"] and not replay["current"]
    # A lost receipt response returns the original booking after promise changes.
    body(await client.post(receive_url, headers=site.headers, json=delivery), 201)
    current = await latest(client, site, payload["line_id"])
    assert (
        current["id"] == replacement["id"] and Decimal(current["remaining_physical_quantity"]) == 4
    )
    stale = await client.post(
        receive_url, headers=site.headers, json={**delivery, "request_key": str(uuid.uuid4())}
    )
    assert stale.status_code == 409


@pytest.mark.asyncio
async def test_unconfirmed_arrival_requires_reason_and_conflict_excludes_incoming(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    order = await ordered(client, site, setup)
    payload = promise(order, paid_quantity="4")
    first = body(
        await client.post(
            site.path("/purchasing/delivery-confirmations"), headers=site.headers, json=payload
        ),
        201,
    )
    delivery = delivery_input(setup, order, accepted_quantity="2")
    url = site.path(f"/purchasing/orders/{order['id']}/receipts")
    assert (await client.post(url, headers=site.headers, json=delivery)).status_code == 409
    body(
        await client.post(
            url,
            headers=site.headers,
            json={
                **delivery,
                "unconfirmed_delivery_reason": "Andere Ersatzlieferung ohne Zusagenbezug",
            },
        ),
        201,
    )
    current = await latest(client, site, first["line_id"])
    assert Decimal(current["remaining_physical_quantity"]) == 4
    assert not current["reliable_for_planning"]
    assert any("Einkaufsrest" in conflict for conflict in current["conflicts"])


@pytest.mark.asyncio
async def test_rejected_arrival_is_not_counted_as_future_incoming_stock(
    client: AsyncClient, site: Site
) -> None:
    setup = await catalog(client, site)
    order = await ordered(client, site, setup)
    confirmed = body(
        await client.post(
            site.path("/purchasing/delivery-confirmations"),
            headers=site.headers,
            json=promise(order),
        ),
        201,
    )
    received = await delivered(
        client,
        site,
        setup,
        order,
        accepted_quantity="1",
        rejected_quantity="2",
        rejection_reason="Temperaturabweichung",
        confirmation_id=confirmed["id"],
    )
    current = await latest(client, site, confirmed["line_id"])
    assert Decimal(current["remaining_physical_quantity"]) == 0
    assert Decimal(current["rejected_quantity"]) == 2 and not current["reliable_for_planning"]
    assert Decimal(received["lines"][0]["remaining_quantity"]) == 4
    stock = body(await client.get(site.path("/inventory/snapshot"), headers=site.headers))
    assert sum(Decimal(row["quantity"]) for row in stock["balances"]) == 1


@pytest.mark.asyncio
async def test_confirmation_roles_scope_duplicate_keys_and_versions(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    setup = await catalog(client, site)
    order = await ordered(client, site, setup)
    payload = promise(order)
    url = site.path("/purchasing/delivery-confirmations")
    assert (
        await client.post(url, headers=hr_workspace.headers("worker"), json=payload)
    ).status_code == 403
    assert (
        await client.post(url, headers=hr_workspace.headers("other_hr"), json=payload)
    ).status_code == 404
    body(await client.post(url, headers=site.headers, json=payload), 201)
    assert (
        await client.post(url, headers=site.headers, json={**payload, "paid_quantity": "2"})
    ).status_code == 409
    assert (await client.post(url, headers=site.headers, json=promise(order))).status_code == 409
    too_many = promise(order, expected_version=1, paid_quantity="6")
    assert (await client.post(url, headers=site.headers, json=too_many)).status_code == 409


def test_new_receipt_defaults_preserve_legacy_pending_hash() -> None:
    import hashlib
    import json

    old = {
        "request_key": str(uuid.uuid4()),
        "reason": "Legacy receipt",
        "line_id": str(uuid.uuid4()),
        "accepted_quantity": "1",
        "rejected_quantity": "0",
        "rejection_reason": "",
        "location_id": str(uuid.uuid4()),
        "lot_code": "ABC",
        "expires_on": None,
        "blocked": False,
        "reference": "LS-1",
    }
    expected = hashlib.sha256(
        json.dumps(old, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert request_digest(PurchaseReceiptInput.model_validate(old)) == expected
    assert (
        request_digest(
            PurchaseReceiptInput.model_validate({**old, "confirmation_id": str(uuid.uuid4())})
        )
        != expected
    )


@pytest.mark.asyncio
async def test_real_delivery_migration_roundtrip_keeps_schema_and_evidence_guards(
    db_session: AsyncSession,
) -> None:
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import Connection, inspect, text
    from sqlalchemy.exc import DBAPIError

    from app.gastro.delivery_models import DeliveryConfirmation

    spec = importlib.util.spec_from_file_location(
        "delivery_migration", Path("alembic/versions/081_flintplate_delivery_confirmations.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def check(connection: Connection) -> None:
        assert (
            connection.execute(text("SELECT current_database()")).scalar_one() == "flintplate_test"
        )
        schema = "delivery_migration_" + uuid.uuid4().hex
        previous_path = connection.execute(text("SHOW search_path")).scalar_one()
        previous_map = connection.get_execution_options().get("schema_translate_map")
        connection.execution_options(schema_translate_map=None)
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        connection.execute(text("SELECT set_config('search_path',:path,true)"), {"path": schema})
        try:
            with (
                connection.begin_nested(),
                Operations.context(MigrationContext.configure(connection)),
            ):
                connection.execute(text("CREATE TABLE users(id uuid PRIMARY KEY)"))
                connection.execute(text("CREATE TABLE fp_venues(id uuid PRIMARY KEY)"))
                connection.execute(
                    text(
                        "CREATE TABLE fp_purchase_order_lines(id uuid PRIMARY KEY, venue_id uuid NOT NULL, UNIQUE(venue_id,id))"
                    )
                )
                connection.execute(text("""CREATE TABLE fp_purchase_receipts(
                        id uuid PRIMARY KEY, venue_id uuid NOT NULL, line_id uuid NOT NULL,
                        accepted_quantity numeric(18,6) NOT NULL DEFAULT 0,
                        rejected_quantity numeric(18,6) NOT NULL DEFAULT 0,
                        accepted_bonus_quantity numeric(18,6) NOT NULL DEFAULT 0,
                        rejected_bonus_quantity numeric(18,6) NOT NULL DEFAULT 0)"""))
                connection.execute(
                    text(
                        "CREATE FUNCTION fp_reject_purchase_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'immutable'; END $$"
                    )
                )
                module.upgrade()
                columns = {
                    c["name"]: c
                    for c in inspect(connection).get_columns(
                        "fp_delivery_confirmations", schema=schema
                    )
                }
                assert set(columns) == set(DeliveryConfirmation.__table__.c.keys())
                for column in DeliveryConfirmation.__table__.c:
                    assert columns[column.name]["nullable"] == column.nullable
                module.downgrade()
                module.upgrade()
                venue, user, line, other_line, record = [uuid.uuid4() for _ in range(5)]
                connection.execute(text("INSERT INTO fp_venues VALUES(:id)"), {"id": venue})
                connection.execute(text("INSERT INTO users VALUES(:id)"), {"id": user})
                for source in (line, other_line):
                    connection.execute(
                        text("INSERT INTO fp_purchase_order_lines VALUES(:id,:venue)"),
                        {"id": source, "venue": venue},
                    )
                insert = text(
                    """INSERT INTO fp_delivery_confirmations
                    (id,venue_id,line_id,actor_id,request_key,request_hash,reason,previous_id,version,status,expected_on,paid_quantity,bonus_quantity,reference)
                    VALUES(:id,:venue,:line,:actor,:key,'abc','Synthetic source',:previous,:version,:status,current_date,:paid,:bonus,'AB-SYNTHETIC')"""
                )
                values = {
                    "id": record,
                    "venue": venue,
                    "line": line,
                    "actor": user,
                    "key": uuid.uuid4(),
                    "previous": None,
                    "version": 1,
                    "status": "confirmed",
                    "paid": Decimal(3),
                    "bonus": Decimal(2),
                }
                connection.execute(insert, values)
                for sql in (
                    "UPDATE fp_delivery_confirmations SET paid_quantity=4",
                    "DELETE FROM fp_delivery_confirmations",
                    "TRUNCATE fp_delivery_confirmations CASCADE",
                ):
                    with pytest.raises(DBAPIError, match="immutable"), connection.begin_nested():
                        connection.execute(text(sql))
                with pytest.raises(DBAPIError, match="current version"), connection.begin_nested():
                    connection.execute(
                        insert, {**values, "id": uuid.uuid4(), "key": uuid.uuid4(), "version": 3}
                    )
                insert_receipt = text("""INSERT INTO fp_purchase_receipts
                    (id,venue_id,line_id,confirmation_id,accepted_quantity,rejected_quantity,
                     accepted_bonus_quantity,rejected_bonus_quantity)
                    VALUES(:id,:venue,:line,:confirmation,:accepted,:rejected,
                           :accepted_bonus,:rejected_bonus)""")
                receipt_values = {
                    "id": uuid.uuid4(),
                    "venue": venue,
                    "line": line,
                    "confirmation": record,
                    "accepted": Decimal(2),
                    "rejected": Decimal(1),
                    "accepted_bonus": Decimal("0.5"),
                    "rejected_bonus": Decimal("0.5"),
                }
                with (
                    pytest.raises(DBAPIError, match="another purchase line"),
                    connection.begin_nested(),
                ):
                    connection.execute(insert_receipt, {**receipt_values, "line": other_line})
                other_venue = uuid.uuid4()
                connection.execute(text("INSERT INTO fp_venues VALUES(:id)"), {"id": other_venue})
                with (
                    pytest.raises(DBAPIError, match="another purchase line"),
                    connection.begin_nested(),
                ):
                    connection.execute(insert_receipt, {**receipt_values, "venue": other_venue})
                # First arrival consumes paid=2 and bonus=1, including rejected goods.
                connection.execute(insert_receipt, receipt_values)
                next_receipt = {
                    **receipt_values,
                    "id": uuid.uuid4(),
                    "accepted": Decimal(0),
                    "rejected": Decimal("1.000001"),
                    "accepted_bonus": Decimal(0),
                    "rejected_bonus": Decimal(0),
                }
                # Each request fits the original promise, but exceeds its cumulative rest.
                with (
                    pytest.raises(DBAPIError, match="arrived quantities exceed"),
                    connection.begin_nested(),
                ):
                    connection.execute(insert_receipt, next_receipt)
                with (
                    pytest.raises(DBAPIError, match="arrived quantities exceed"),
                    connection.begin_nested(),
                ):
                    connection.execute(
                        insert_receipt,
                        {**next_receipt, "rejected_bonus": Decimal("1.000001")},
                    )
                # Rejection of the exact paid=1/bonus=1 remainder is a valid real arrival.
                connection.execute(
                    insert_receipt,
                    {**next_receipt, "rejected": Decimal(2), "rejected_bonus": Decimal(1)},
                )
                totals = connection.execute(
                    text("""SELECT sum(accepted_quantity + rejected_quantity),
                                  sum(accepted_bonus_quantity + rejected_bonus_quantity)
                           FROM fp_purchase_receipts WHERE confirmation_id=:confirmation"""),
                    {"confirmation": record},
                ).one()
                assert totals == (Decimal(5), Decimal(2))
                replacement = uuid.uuid4()
                connection.execute(
                    insert,
                    {
                        **values,
                        "id": replacement,
                        "key": uuid.uuid4(),
                        "previous": record,
                        "version": 2,
                    },
                )
                with (
                    pytest.raises(DBAPIError, match="current confirmed delivery revision"),
                    connection.begin_nested(),
                ):
                    connection.execute(insert_receipt, {**next_receipt, "id": uuid.uuid4()})
                # Arrivals against older revisions do not consume a replacement promise.
                connection.execute(
                    insert_receipt,
                    {**receipt_values, "id": uuid.uuid4(), "confirmation": replacement},
                )
                cancelled = uuid.uuid4()
                connection.execute(
                    insert,
                    {
                        **values,
                        "id": cancelled,
                        "key": uuid.uuid4(),
                        "previous": replacement,
                        "version": 3,
                        "status": "cancelled",
                        "paid": Decimal(0),
                        "bonus": Decimal(0),
                    },
                )
                with (
                    pytest.raises(DBAPIError, match="current confirmed delivery revision"),
                    connection.begin_nested(),
                ):
                    connection.execute(
                        insert_receipt,
                        {**next_receipt, "id": uuid.uuid4(), "confirmation": cancelled},
                    )
                # Unattributed arrivals remain available for the explicit API exception path.
                connection.execute(
                    insert_receipt,
                    {**next_receipt, "id": uuid.uuid4(), "confirmation": None},
                )
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM fp_purchase_receipts")
                    ).scalar_one()
                    == 4
                )
                with (
                    pytest.raises(DBAPIError, match="destructive downgrade"),
                    connection.begin_nested(),
                ):
                    module.downgrade()
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM fp_delivery_confirmations")
                    ).scalar_one()
                    == 3
                )
        finally:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            connection.execute(
                text("SELECT set_config('search_path',:path,true)"), {"path": previous_path}
            )
            connection.execution_options(schema_translate_map=previous_map)

    await (await db_session.connection()).run_sync(check)
