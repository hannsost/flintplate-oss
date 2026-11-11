"""Approved unit claims conserve money without first collecting the rest of a bill."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.cash_models import CashEntry
from app.gastro.models import DeviceReceipt, Order, Voucher
from app.gastro.schemas import MenuPayload
from tests.cancellation_support import approve_cancellation
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, pos_device, sent_order, serve
from tests.test_flintplate_cash import install_cash_guards, payment, till

pytest_plugins = ["tests.test_flintplate"]


async def current_balance(client: AsyncClient, site: Site, order: dict) -> dict:
    return body(await client.get(site.path(f"/orders/{order['id']}/balance"), headers=site.headers))


async def payout(
    client: AsyncClient, site: Site, claim: dict, session: dict, amount: int, **extra: object
) -> dict:
    return body(
        await client.post(
            site.path(f"/cash/payments/{claim['original_id']}/refunds"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "cancellation_id": claim["cancellation_id"],
                "amount_cents": amount,
                "session_id": session["id"],
                "reason": "Actual synthetic return",
                "confirmed": True,
                **extra,
            },
        ),
        201,
    )


@pytest.mark.asyncio
async def test_partial_tender_cancellation_and_payout_leave_remaining_bill_payable(
    client: AsyncClient,
    site: Site,
    hr_workspace: HRWorkspace,
    db_session: AsyncSession,
) -> None:
    session = await till(client, site, hr_workspace)
    order = await serve(client, site, await sent_order(client, site))
    order = await payment(client, site, order, session, 500)
    await install_cash_guards(db_session)
    before = await current_balance(client, site, order)
    cancelled = await approve_cancellation(
        client, site, order, lines=[{"line_id": order["lines"][0]["line_id"], "quantity": 1}]
    )
    assert cancelled["money"]["unpaid_credit_cents"] == 750
    assert cancelled["money"]["refund_due_cents"] == 250
    state = await current_balance(client, site, order)
    assert state["remaining_cents"] == 750 and state["paid_cents"] == 500
    assert state["corrected_total_cents"] == 1000 and state["refunded_cents"] == 0
    assert len(state["entries"]) == len(before["entries"])  # Approval never pays out.
    claim = state["refund_claims"][0]
    first = await payout(client, site, claim, session, 1)
    second = await payout(client, site, claim, session, 249)
    assert {a["unit"] for entry in (first, second) for a in entry["allocations"]} == {0}
    assert (
        sum(a["tax_cents"] for entry in (first, second) for a in entry["allocations"])
        == claim["tax_cents"]
    )
    state = await current_balance(client, site, order)
    assert state["remaining_cents"] == 750 and state["refund_due_cents"] == 0
    current = body(await client.get(site.path(f"/orders/{order['id']}"), headers=site.headers))
    assert current["paid_at"] is None and current["lines"] == order["lines"]
    settled = await payment(client, site, current, session, 750)
    assert settled["paid_at"] and settled["payment_status"] == "paid"
    after = await current_balance(client, site, order)
    assert after["remaining_cents"] == 0
    assert sum(entry["amount_cents"] for entry in after["entries"]) == 1000
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.asyncio
async def test_full_partial_paid_cancellation_has_no_forced_settlement_or_fake_payout(
    client: AsyncClient,
    site: Site,
    hr_workspace: HRWorkspace,
    db_session: AsyncSession,
) -> None:
    session = await till(client, site, hr_workspace)
    order = await payment(
        client, site, await serve(client, site, await sent_order(client, site)), session, 501
    )
    await install_cash_guards(db_session)
    await approve_cancellation(client, site, order, whole=True)
    state = await current_balance(client, site, order)
    assert state["remaining_cents"] == 0 and state["refund_due_cents"] == 501
    assert state["unpaid_credit_cents"] == 1499 and state["refunded_cents"] == 0
    current = body(await client.get(site.path(f"/orders/{order['id']}"), headers=site.headers))
    assert current["paid_at"] is None and current["payment_status"] == "refund_pending"
    await payout(client, site, state["refund_claims"][0], session, 501)
    current = body(await client.get(site.path(f"/orders/{order['id']}"), headers=site.headers))
    assert current["paid_at"] is None and current["payment_status"] == "refunded"
    assert (await current_balance(client, site, order))["remaining_cents"] == 0
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.asyncio
async def test_refunds_require_approval_actual_confirmation_and_matching_source(
    client: AsyncClient,
    site: Site,
    hr_workspace: HRWorkspace,
) -> None:
    session = await till(client, site, hr_workspace)
    order = await payment(
        client, site, await serve(client, site, await sent_order(client, site)), session, 500
    )
    source = (await current_balance(client, site, order))["entries"][0]
    data = {
        "request_key": str(uuid.uuid4()),
        "amount_cents": 100,
        "session_id": session["id"],
        "reason": "Refund test",
        "confirmed": True,
    }
    path = site.path(f"/cash/payments/{source['id']}/refunds")
    assert (await client.post(path, headers=site.headers, json=data)).status_code == 409
    cancelled = await approve_cancellation(client, site, order, whole=True)
    assert (
        await client.post(
            path,
            headers=site.headers,
            json={**data, "cancellation_id": cancelled["id"], "confirmed": False},
        )
    ).status_code == 422
    assert (
        await client.post(
            path,
            headers=hr_workspace.headers("worker"),
            json={**data, "cancellation_id": cancelled["id"]},
        )
    ).status_code == 403
    assert (
        await client.post(
            path, headers=site.headers, json={**data, "cancellation_id": str(uuid.uuid4())}
        )
    ).status_code == 409
    result = body(
        await client.post(
            path, headers=site.headers, json={**data, "cancellation_id": cancelled["id"]}
        ),
        201,
    )
    repeated = body(
        await client.post(
            path, headers=site.headers, json={**data, "cancellation_id": cancelled["id"]}
        ),
        201,
    )
    assert repeated["id"] == result["id"]
    assert (
        await client.post(
            path,
            headers=site.headers,
            json={**data, "cancellation_id": cancelled["id"], "amount_cents": 101},
        )
    ).status_code == 409
    assert (
        await client.post(
            path,
            headers=site.headers,
            json={
                **data,
                "request_key": str(uuid.uuid4()),
                "cancellation_id": cancelled["id"],
                "amount_cents": 401,
            },
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_external_checkout_requires_explicit_current_ack_and_rejects_late_old_payment(
    client: AsyncClient,
    site: Site,
    db_session: AsyncSession,
) -> None:
    device = await pos_device(client, site)
    headers = {"X-FlintPlate-Key": device["token"]}
    order = await serve(client, site, await sent_order(client, site))
    order = body(
        await client.post(
            site.path(f"/orders/{order['id']}/checkout"),
            headers=site.headers,
            json={"version": order["version"]},
        )
    )
    await install_cash_guards(db_session)
    cancelled = await approve_cancellation(
        client, site, order, lines=[{"line_id": order["lines"][0]["line_id"], "quantity": 1}]
    )
    balance = await current_balance(client, site, order)
    assert balance["checkout_blocked"] and balance["remaining_cents"] == 1000
    payment_data = {
        "request_key": str(uuid.uuid4()),
        "order_id": order["id"],
        "amount_cents": 1000,
        "reference": "payment-proof",
        "currency": "EUR",
    }
    assert (
        await client.post("/device/v1/payments", headers=headers, json=payment_data)
    ).status_code == 409
    ack = {
        "request_key": str(uuid.uuid4()),
        "version": balance["version"],
        "cancellation_version": cancelled["result_version"],
        "remaining_cents": 1000,
        "cancelled_cents": 1000,
        "reference": "adapter confirmed old checkout void",
        "confirmed": True,
        "no_pending_payments": True,
    }
    ack_path = f"/device/v1/orders/{order['id']}/checkout-corrections"
    assert (
        await client.post(ack_path, headers=headers, json={**ack, "remaining_cents": 999})
    ).status_code == 409
    first = body(await client.post(ack_path, headers=headers, json=ack), 201)
    assert body(await client.post(ack_path, headers=headers, json=ack), 201)["id"] == first["id"]
    assert not (await current_balance(client, site, order))["checkout_blocked"]
    assert (
        await client.post("/device/v1/payments", headers=headers, json=payment_data)
    ).status_code == 409
    paid = body(
        await client.post(
            "/device/v1/payments",
            headers=headers,
            json={**payment_data, "cancellation_version": cancelled["result_version"]},
        )
    )
    assert paid["payment_status"] == "paid"
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.asyncio
async def test_new_cancellation_reblocks_an_already_acknowledged_adapter(
    client: AsyncClient,
    site: Site,
) -> None:
    device = await pos_device(client, site)
    headers = {"X-FlintPlate-Key": device["token"]}
    order = await serve(client, site, await sent_order(client, site))
    order = body(
        await client.post(
            site.path(f"/orders/{order['id']}/checkout"),
            headers=site.headers,
            json={"version": order["version"]},
        )
    )
    first = await approve_cancellation(
        client, site, order, lines=[{"line_id": order["lines"][0]["line_id"], "quantity": 1}]
    )
    balance = await current_balance(client, site, order)
    data = {
        "request_key": str(uuid.uuid4()),
        "version": balance["version"],
        "cancellation_version": first["result_version"],
        "remaining_cents": 1000,
        "cancelled_cents": 1000,
        "reference": "first void confirmation",
        "confirmed": True,
        "no_pending_payments": True,
    }
    path = f"/device/v1/orders/{order['id']}/checkout-corrections"
    body(await client.post(path, headers=headers, json=data), 201)
    await approve_cancellation(client, site, order, whole=True)
    body(
        await client.post(path, headers=headers, json=data), 201
    )  # Historical replay does not acknowledge a newer correction.
    assert (await current_balance(client, site, order))["checkout_blocked"]


@pytest.mark.asyncio
async def test_database_rejects_unapproved_or_forged_unit_refunds_and_new_cancelled_charges(
    client: AsyncClient,
    site: Site,
    hr_workspace: HRWorkspace,
    db_session: AsyncSession,
) -> None:
    session = await till(client, site, hr_workspace)
    order = await payment(
        client, site, await serve(client, site, await sent_order(client, site)), session, 500
    )
    await install_cash_guards(db_session)
    source = (await current_balance(client, site, order))["entries"][0]
    allocation = {**source["allocations"][0], "amount_cents": 1, "tax_cents": 0}

    async def forged(kind: str, value: dict) -> None:
        await db_session.execute(
            text(
                """INSERT INTO fp_cash_entries
          (id,venue_id,order_id,session_id,original_id,kind,method,amount_cents,currency,allocations,
           actor_id,request_key,request_hash,reason)
          VALUES (:id,:venue,:order,:session,:original,:kind,'cash',:amount,'EUR',CAST(:allocations AS jsonb),:actor,:key,'forged','direct SQL test')"""
            ),
            {
                "id": uuid.uuid4(),
                "venue": site.venue_id,
                "order": order["id"],
                "session": session["id"],
                "original": source["id"] if kind == "refund" else None,
                "kind": kind,
                "amount": (
                    -int(value.get("amount_cents", 1))
                    if kind == "refund"
                    else int(value.get("amount_cents", 1))
                ),
                "allocations": json.dumps([value]),
                "actor": hr_workspace.hr.id,
                "key": uuid.uuid4(),
            },
        )

    with pytest.raises(DBAPIError, match="Cancellation"):
        async with db_session.begin_nested():
            await forged("refund", allocation)
    cancelled = await approve_cancellation(
        client, site, order, lines=[{"line_id": order["lines"][0]["line_id"], "quantity": 1}]
    )
    for malformed in (
        {**allocation, "cancellation_id": cancelled["id"], "tax_cents": 1},
        {**allocation, "cancellation_id": cancelled["id"], "unit": 1},
        {**allocation, "cancellation_id": cancelled["id"], "kind": "tip"},
        {key: value for key, value in allocation.items() if key != "tax_cents"},
    ):
        with pytest.raises(DBAPIError, match="Cancellation"):
            async with db_session.begin_nested():
                await forged("refund", malformed)
    with pytest.raises(DBAPIError, match="Cancellation"):
        async with db_session.begin_nested():
            await forged("sale", allocation)
    with pytest.raises(DBAPIError, match="snapshot"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE fp_orders SET total_cents=1 WHERE id=:id"), {"id": order["id"]}
            )
    with pytest.raises(DBAPIError, match="ledger"):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE fp_orders SET paid_at=now(),payment_status='paid' WHERE id=:id"),
                {"id": order["id"]},
            )
            await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.asyncio
async def test_direct_unit_insert_cannot_forge_balanced_credits_or_refund_sources(
    client: AsyncClient,
    site: Site,
    hr_workspace: HRWorkspace,
    db_session: AsyncSession,
) -> None:
    session = await till(client, site, hr_workspace)
    order = await payment(
        client, site, await serve(client, site, await sent_order(client, site)), session, 500
    )
    preview = body(
        await client.post(
            site.path(f"/orders/{order['id']}/cancellations/preview"),
            headers=site.headers,
            json={
                "version": order["version"],
                "whole_order": True,
                "reason_code": "guest_request",
                "note": "Synthetic original money projection",
            },
        )
    )
    second = next(row for row in preview["money"]["units"] if row["unit"] == 1)
    await install_cash_guards(db_session)
    cancelled = await approve_cancellation(
        client, site, order, lines=[{"line_id": order["lines"][0]["line_id"], "quantity": 1}]
    )
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    for false_projection, expected in (
        (
            {
                **second,
                "unpaid_credit_cents": second["unpaid_credit_cents"] + 1,
                "refund_due_cents": second["refund_due_cents"] - 1,
                "refund_allocations": [
                    {
                        **second["refund_allocations"][0],
                        "amount_cents": second["refund_allocations"][0]["amount_cents"] - 1,
                    }
                ],
            },
            "money projection not proven",
        ),
        (
            {
                **second,
                "refund_allocations": [
                    {**second["refund_allocations"][0], "original_id": str(uuid.uuid4())}
                ],
            },
            "refund claim not proven",
        ),
    ):
        # Both forgeries conserve gross/tax and satisfy table constraints. The
        # money trigger must independently prove the split against original Sales.
        with pytest.raises(DBAPIError, match=expected):
            async with db_session.begin_nested():
                await db_session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
                await db_session.execute(
                    text("""INSERT INTO fp_cancellation_units
                        (id,venue_id,order_id,execution_id,line_id,unit,kind,name,
                         gross_cents,tax_cents,unpaid_credit_cents,unpaid_tax_cents,
                         refund_due_cents,refund_tax_cents,already_refunded_cents,
                         already_refunded_tax_cents,refund_allocations)
                        VALUES (:id,:venue,:order,:execution,:line_id,:unit,:kind,:name,
                         :gross_cents,:tax_cents,:unpaid_credit_cents,:unpaid_tax_cents,
                         :refund_due_cents,:refund_tax_cents,:already_refunded_cents,
                         :already_refunded_tax_cents,CAST(:refund_allocations AS jsonb))"""),
                    {
                        **false_projection,
                        "id": uuid.uuid4(),
                        "venue": site.venue_id,
                        "order": order["id"],
                        "execution": cancelled["id"],
                        "refund_allocations": json.dumps(false_projection["refund_allocations"]),
                    },
                )
                await db_session.execute(
                    text("SET CONSTRAINTS fp_cancellation_units_cancellation_money IMMEDIATE")
                )
    assert (await current_balance(client, site, order))["cancelled_cents"] == 1000


@pytest.mark.asyncio
async def test_external_selected_refund_needs_original_claim_current_ack_and_actual_confirmation(
    client: AsyncClient,
    site: Site,
    db_session: AsyncSession,
) -> None:
    device = await pos_device(client, site)
    headers = {"X-FlintPlate-Key": device["token"]}
    order = await serve(client, site, await sent_order(client, site))
    body(
        await client.post(
            site.path(f"/orders/{order['id']}/checkout"),
            headers=site.headers,
            json={"version": order["version"]},
        )
    )
    body(
        await client.post(
            "/device/v1/payments",
            headers=headers,
            json={
                "request_key": str(uuid.uuid4()),
                "order_id": order["id"],
                "amount_cents": 500,
                "reference": "Synthetic original external tender",
                "currency": "EUR",
            },
        )
    )
    await install_cash_guards(db_session)
    cancelled = await approve_cancellation(
        client, site, order, lines=[{"line_id": order["lines"][0]["line_id"], "quantity": 1}]
    )
    balance = await current_balance(client, site, order)
    claim = balance["refund_claims"][0]
    assert claim["method"] == "external" and claim["remaining_cents"] == 250
    data = {
        "request_key": str(uuid.uuid4()),
        "original_id": claim["original_id"],
        "cancellation_id": cancelled["id"],
        "cancellation_version": cancelled["result_version"],
        "amount_cents": 100,
        "reference": "Synthetic external refund 1",
        "reason": "Confirmed synthetic selected-unit return",
        "confirmed": True,
    }
    assert (await client.post("/device/v1/refunds", json=data)).status_code == 401
    assert (
        await client.post("/device/v1/refunds", headers=headers, json={**data, "confirmed": False})
    ).status_code == 422
    assert (await client.post("/device/v1/refunds", headers=headers, json=data)).status_code == 409
    body(
        await client.post(
            f"/device/v1/orders/{order['id']}/checkout-corrections",
            headers=headers,
            json={
                "request_key": str(uuid.uuid4()),
                "version": balance["version"],
                "cancellation_version": cancelled["result_version"],
                "remaining_cents": balance["remaining_cents"],
                "cancelled_cents": balance["cancelled_cents"],
                "reference": "Synthetic terminal reconciled before refund",
                "confirmed": True,
                "no_pending_payments": True,
            },
        ),
        201,
    )
    for changed in (
        {"cancellation_version": cancelled["result_version"] - 1},
        {"cancellation_id": str(uuid.uuid4())},
    ):
        assert (
            await client.post("/device/v1/refunds", headers=headers, json={**data, **changed})
        ).status_code == 409
    assert (
        await client.post(
            site.path(f"/cash/payments/{claim['original_id']}/refunds"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "cancellation_id": cancelled["id"],
                "amount_cents": 100,
                "reason": "Must not convert external tender into local cash",
                "confirmed": True,
            },
        )
    ).status_code == 409
    first = body(await client.post("/device/v1/refunds", headers=headers, json=data), 201)
    assert (
        body(await client.post("/device/v1/refunds", headers=headers, json=data), 201)["id"]
        == first["id"]
    )
    next_data = {
        **data,
        "request_key": str(uuid.uuid4()),
        "reference": "Synthetic external refund 2",
        "amount_cents": 151,
    }
    assert (
        await client.post("/device/v1/refunds", headers=headers, json=next_data)
    ).status_code == 409
    second = body(
        await client.post(
            "/device/v1/refunds", headers=headers, json={**next_data, "amount_cents": 150}
        ),
        201,
    )
    assert {row["unit"] for entry in (first, second) for row in entry["allocations"]} == {0}
    assert (
        sum(row["tax_cents"] for entry in (first, second) for row in entry["allocations"])
        == claim["tax_cents"]
    )
    balance = await current_balance(client, site, order)
    assert balance["remaining_cents"] == 750 and balance["refund_due_cents"] == 0
    assert sum(row["amount_cents"] for row in balance["entries"]) == 250
    current = body(await client.get(site.path(f"/orders/{order['id']}"), headers=site.headers))
    assert current["paid_at"] is None and current["lines"] == order["lines"]
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.asyncio
async def test_legacy_unpaid_receipt_keeps_uuid5_units_through_cancellation_and_payment(
    client: AsyncClient,
    site: Site,
    hr_workspace: HRWorkspace,
    db_session: AsyncSession,
) -> None:
    session = await till(client, site, hr_workspace)
    order = await serve(client, site, await sent_order(client, site))
    stored = await db_session.get(Order, uuid.UUID(order["id"]))
    assert stored is not None
    # Synthetic pre-ID receipt, established before the immutable guards exist.
    original_lines = [
        {key: value for key, value in line.items() if key != "line_id"} for line in stored.lines
    ]
    stored.lines = original_lines
    await db_session.flush()
    await install_cash_guards(db_session)
    legacy_id = str(uuid.uuid5(stored.id, "line:0"))
    sql_id = await db_session.scalar(
        text("SELECT fp_cash_line_id(:id,0,CAST(:line AS jsonb))"),
        {"id": stored.id, "line": json.dumps(original_lines[0])},
    )
    assert sql_id == legacy_id
    before = await current_balance(client, site, order)
    assert before["lines"][0]["line_id"] == legacy_id and before["remaining_cents"] == 2000
    cancelled = await approve_cancellation(
        client, site, order, lines=[{"line_id": legacy_id, "quantity": 1}]
    )
    assert cancelled["money"]["unpaid_credit_cents"] == 1000
    assert cancelled["money"]["refund_due_cents"] == 0
    current = body(await client.get(site.path(f"/orders/{order['id']}"), headers=site.headers))
    settled = await payment(client, site, current, session, 1000)
    assert settled["paid_at"] and settled["payment_status"] == "paid"
    balance = await current_balance(client, site, order)
    assert balance["remaining_cents"] == 0 and balance["corrected_total_cents"] == 1000
    assert balance["entries"][0]["allocations"][0]["line_id"] == legacy_id
    assert balance["entries"][0]["allocations"][0]["unit"] == 1
    await db_session.refresh(stored)
    assert stored.lines == original_lines and stored.total_cents == 2000
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.asyncio
async def test_legacy_device_payment_hash_replays_without_new_sale_or_new_privileges(
    client: AsyncClient,
    site: Site,
    db_session: AsyncSession,
) -> None:
    device = await pos_device(client, site)
    order = await serve(client, site, await sent_order(client, site))
    body(
        await client.post(
            site.path(f"/orders/{order['id']}/checkout"),
            headers=site.headers,
            json={"version": order["version"]},
        )
    )
    payload = {
        "request_key": str(uuid.uuid4()),
        "order_id": order["id"],
        "amount_cents": 2000,
        "reference": "historic proof",
        "currency": "EUR",
    }
    headers = {"X-FlintPlate-Key": device["token"]}
    body(await client.post("/device/v1/payments", headers=headers, json=payload))
    receipt = (
        await db_session.execute(
            select(DeviceReceipt).where(
                DeviceReceipt.request_key == uuid.UUID(payload["request_key"])
            )
        )
    ).scalar_one()
    receipt.request_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    await db_session.flush()
    replay = body(await client.post("/device/v1/payments", headers=headers, json=payload))
    assert replay["paid_at"]
    assert len((await current_balance(client, site, order))["entries"]) == 1
    assert (
        await client.post(
            "/device/v1/payments", headers=headers, json={**payload, "amount_cents": 1999}
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_legacy_refund_hash_replays_but_cannot_authorize_a_new_unrefereced_payout(
    client: AsyncClient,
    site: Site,
    hr_workspace: HRWorkspace,
    db_session: AsyncSession,
) -> None:
    session = await till(client, site, hr_workspace)
    order = await payment(
        client, site, await serve(client, site, await sent_order(client, site)), session, 2000
    )
    source = (await current_balance(client, site, order))["entries"][0]
    cancelled = await approve_cancellation(client, site, order, whole=True)
    payload = {
        "request_key": str(uuid.uuid4()),
        "amount_cents": 100,
        "session_id": session["id"],
        "reason": "Actual old refund",
    }
    path = site.path(f"/cash/payments/{source['id']}/refunds")
    returned = body(
        await client.post(
            path,
            headers=site.headers,
            json={**payload, "cancellation_id": cancelled["id"], "confirmed": True},
        ),
        201,
    )
    entry = await db_session.get(CashEntry, uuid.UUID(returned["id"]))
    assert entry is not None
    entry.request_hash = hashlib.sha256(
        json.dumps(["refund", source["id"], payload], sort_keys=True).encode()
    ).hexdigest()
    await db_session.flush()
    replay = body(await client.post(path, headers=site.headers, json=payload), 201)
    assert replay["id"] == returned["id"]
    assert (
        await client.post(
            path, headers=site.headers, json={**payload, "request_key": str(uuid.uuid4())}
        )
    ).status_code == 422


@pytest.mark.asyncio
async def test_selected_tip_is_not_distributed_while_approved_refund_remains_unpaid(
    client: AsyncClient,
    site: Site,
    hr_workspace: HRWorkspace,
    db_session: AsyncSession,
) -> None:
    from app.gastro.tips import available_tip_cents

    session = await till(client, site, hr_workspace)
    order = await sent_order(client, site)
    order = body(
        await client.post(
            site.path(f"/orders/{order['id']}/tip"),
            headers=site.headers,
            json={"version": order["version"], "tip_cents": 200},
        )
    )
    order = await payment(client, site, await serve(client, site, order), session, 2200)
    await approve_cancellation(client, site, order, include_tip=True)
    stored = await db_session.get(Order, uuid.UUID(order["id"]))
    assert stored is not None and stored.tip_refunded_cents == 0
    assert available_tip_cents(stored) == 0
    state = await current_balance(client, site, order)
    assert state["refund_due_cents"] == 200 and state["remaining_tip_cents"] == 0


@pytest.mark.asyncio
async def test_free_remaining_unit_is_not_a_full_cancellation_or_a_paid_timestamp(
    client: AsyncClient,
    site: Site,
    hr_workspace: HRWorkspace,
    db_session: AsyncSession,
) -> None:
    await till(client, site, hr_workspace)
    free = body(
        await client.post(
            site.path("/menu"),
            headers=site.headers,
            json={
                "sku": "FREE",
                "data": MenuPayload(
                    name="Free sample", price_cents=0, tax_rate_bps=1900, cost_cents=0
                ).model_dump(mode="json"),
            },
        ),
        201,
    )
    body(
        await client.post(
            site.path(f"/menu/{free['id']}/publish"), headers=site.headers, json={"version": 1}
        )
    )
    order = await sent_order(
        client,
        site,
        lines=[
            {"item_id": site.item_id, "menu_version": 1, "quantity": 1},
            {"item_id": free["id"], "menu_version": 1, "quantity": 1},
        ],
    )
    await install_cash_guards(db_session)
    await approve_cancellation(
        client, site, order, lines=[{"line_id": order["lines"][0]["line_id"], "quantity": 1}]
    )
    current = body(await client.get(site.path(f"/orders/{order['id']}"), headers=site.headers))
    assert current["payment_status"] == "adjusted" and current["paid_at"] is None
    assert current["fulfillment_status"] != "cancelled"
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.asyncio
async def test_reserved_voucher_is_previewed_without_write_and_refunded_only_to_its_source(
    client: AsyncClient,
    site: Site,
    hr_workspace: HRWorkspace,
    db_session: AsyncSession,
) -> None:
    session = await till(client, site, hr_workspace)
    voucher = body(
        await client.post(
            site.path("/vouchers"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "label": "Source only",
                "amount_cents": 1000,
                "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat(),
                "reference": "Synthetic voucher receipt",
            },
        ),
        201,
    )
    order = await sent_order(client, site)
    order = body(
        await client.post(
            site.path(f"/orders/{order['id']}/voucher"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "version": order["version"],
                "code": voucher["code"],
                "amount_cents": 800,
            },
        )
    )
    order = await serve(client, site, order)
    await install_cash_guards(db_session)
    selection = {
        "version": order["version"],
        "lines": [{"line_id": order["lines"][0]["line_id"], "quantity": 1}],
        "reason_code": "guest_request",
        "note": "Only selected voucher unit",
    }
    preview = body(
        await client.post(
            site.path(f"/orders/{order['id']}/cancellations/preview"),
            headers=site.headers,
            json=selection,
        )
    )
    assert (
        preview["money"]["refund_due_cents"] == 400
        and preview["money"]["unpaid_credit_cents"] == 600
    )
    assert (await current_balance(client, site, order))["entries"] == []
    await approve_cancellation(client, site, order, lines=selection["lines"])
    state = await current_balance(client, site, order)
    assert len(state["entries"]) == 1 and state["entries"][0]["method"] == "voucher"
    assert state["remaining_cents"] == 600 and state["refund_claims"][0]["method"] == "voucher"
    await payout(client, site, state["refund_claims"][0], session, 400)
    original = await db_session.get(Voucher, uuid.UUID(voucher["voucher"]["id"]))
    assert original is not None and original.balance_cents == 600
    current = body(await client.get(site.path(f"/orders/{order['id']}"), headers=site.headers))
    await payment(client, site, current, session, 600)
    state = await current_balance(client, site, order)
    assert (
        state["remaining_cents"] == 0
        and sum(row["amount_cents"] for row in state["entries"]) == 1000
    )
    assert (
        len(
            [
                row
                for row in state["entries"]
                if row["method"] == "voucher" and row["kind"] == "sale"
            ]
        )
        == 1
    )
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.asyncio
async def test_tip_setter_cannot_rewrite_a_partially_cancelled_original_before_checkout(
    client: AsyncClient,
    site: Site,
) -> None:
    order = await sent_order(client, site)
    await approve_cancellation(
        client, site, order, lines=[{"line_id": order["lines"][0]["line_id"], "quantity": 1}]
    )
    current = body(await client.get(site.path(f"/orders/{order['id']}"), headers=site.headers))
    assert not current["pos_requested"] and current["paid_at"] is None
    response = await client.post(
        site.path(f"/orders/{order['id']}/tip"),
        headers=site.headers,
        json={"version": current["version"], "tip_cents": 1},
    )
    assert response.status_code == 409 and "Stornobelege" in response.text


def test_historical_cancelled_without_tender_has_no_new_receivable_or_invented_claim() -> None:
    from app.gastro.cash import balance_read

    order = Order(
        id=uuid.uuid4(),
        version=1,
        status="cancelled",
        total_cents=1000,
        tip_cents=0,
        voucher_cents=0,
        paid_at=None,
        lines=[
            {
                "line_id": str(uuid.uuid4()),
                "name": "Historic",
                "kind": "product",
                "quantity": 1,
                "total_cents": 1000,
                "tax_cents": 160,
            }
        ],
    )
    result = balance_read(order, [])
    assert (
        result.historical_cancelled
        and result.corrected_total_cents == 0
        and result.remaining_cents == 0
    )
    assert result.lines[0].remaining_quantity == 0 and result.refund_claims == []
    assert order.cancellation_units == [] and order.total_cents == 1000
    order.paid_at = datetime.now(UTC)
    paid = balance_read(order, [])
    assert not paid.historical_cancelled and paid.corrected_total_cents == 1000


@pytest.mark.asyncio
async def test_adjustment_cannot_be_relabelled_as_a_new_payment_by_sql_or_zero_tender(
    client: AsyncClient,
    site: Site,
    hr_workspace: HRWorkspace,
    db_session: AsyncSession,
) -> None:
    session = await till(client, site, hr_workspace)
    other = body(
        await client.post(
            site.path("/menu"),
            headers=site.headers,
            json={
                "sku": "OTHER",
                "data": MenuPayload(
                    name="Other item", price_cents=1000, tax_rate_bps=1900, cost_cents=0
                ).model_dump(mode="json"),
            },
        ),
        201,
    )
    body(
        await client.post(
            site.path(f"/menu/{other['id']}/publish"), headers=site.headers, json={"version": 1}
        )
    )
    order = await serve(
        client,
        site,
        await sent_order(
            client,
            site,
            lines=[
                {"item_id": site.item_id, "menu_version": 1, "quantity": 1},
                {"item_id": other["id"], "menu_version": 1, "quantity": 1},
            ],
        ),
    )
    # Pay the first position exactly, then cancel the wholly unpaid second one.
    order = await payment(
        client,
        site,
        order,
        session,
        0,
        mode="items",
        items=[{"line_id": order["lines"][0]["line_id"], "quantity": 1}],
    )
    source = (
        await db_session.execute(
            select(CashEntry).where(
                CashEntry.order_id == uuid.UUID(order["id"]), CashEntry.kind == "sale"
            )
        )
    ).scalar_one()
    await install_cash_guards(db_session)
    await approve_cancellation(
        client, site, order, lines=[{"line_id": order["lines"][1]["line_id"], "quantity": 1}]
    )
    current = body(await client.get(site.path(f"/orders/{order['id']}"), headers=site.headers))
    assert current["payment_status"] == "adjusted" and current["paid_at"] is None
    with pytest.raises(DBAPIError, match="positive current sale"):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "UPDATE fp_orders SET paid_at=now(),payment_status='paid',payment_reference=:ref WHERE id=:id"
                ),
                {"id": order["id"], "ref": f"cash-ledger:{source.id}"},
            )
    result = await client.post(
        site.path(f"/orders/{order['id']}/cash-payments"),
        headers=site.headers,
        json={
            "request_key": str(uuid.uuid4()),
            "version": current["version"],
            "session_id": session["id"],
            "amount_cents": 0,
        },
    )
    assert result.status_code == 409
