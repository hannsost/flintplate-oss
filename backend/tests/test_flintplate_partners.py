"""Consignment custody, proven sales, nonlinear settlement corrections and deposits."""

from __future__ import annotations

import asyncio
import importlib.util
import uuid
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.database import get_db
from app.gastro import partners
from app.gastro.cash_models import CashEntry
from app.gastro.models import Membership, Venue
from app.gastro.partners_models import PartnerSettlement
from app.main import app
from app.security import create_access_token
from app.users.models import User
from tests.cancellation_support import approve_cancellation
from tests.conftest import TestSessionLocal
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, sent_order, serve
from tests.test_flintplate_cash import payment, till
from tests.test_flintplate_inventory import balances, prepare, received
from tests.utils import auth_headers

pytest_plugins = ["tests.test_flintplate"]


@pytest.mark.asyncio
async def test_partner_contract_cannot_reassign_a_recipe_menu_item(
    client: AsyncClient, site: Site
) -> None:
    stock = await prepare(client, site)
    output = body(
        await client.post(
            site.path("/inventory/items"),
            headers=site.headers,
            json={"sku": "RECIPE-OUT", "name": "Rezeptgericht", "unit": "piece"},
        ),
        201,
    )
    body(
        await client.post(
            site.path("/recipes"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "name": "Bestehende Eigenwarenrezeptur",
                "menu_item_id": site.item_id,
                "menu_version": 1,
                "output_item_id": output["id"],
                "yield_quantity": "1",
                "components": [
                    {
                        "stock_item_id": stock["item_id"],
                        "quantity": "0.2",
                        "unit_cost_cents": 100,
                    }
                ],
                "allergen_reviewed": True,
            },
        ),
        201,
    )
    owner = body(
        await client.post(
            site.path("/inventory/owners"),
            headers=site.headers,
            json={"name": "Separater Partner", "kind": "partner"},
        ),
        201,
    )
    result = await client.post(
        site.path("/partners/contracts"),
        headers=site.headers,
        json={
            "request_key": str(uuid.uuid4()),
            "reason": "Widersprüchliche Zuweisung verhindern",
            "name": "Nicht gleichzeitig Partnerware",
            "owner_id": owner["id"],
            "item_id": stock["item_id"],
            "menu_item_id": site.item_id,
            "effective_on": date.today().replace(day=1).isoformat(),
            "stock_per_sale": "1",
            "rules": {},
        },
    )
    assert result.status_code == 409 and "Rezeptur" in result.json()["detail"]


def path(site: Site, suffix: str) -> str:
    return site.path("/partners" + suffix)


async def setup_partner(client: AsyncClient, site: Site, **changes: object) -> dict:
    stock = await prepare(client, site)
    partner = body(
        await client.post(
            site.path("/inventory/owners"),
            headers=site.headers,
            json={"name": "Winzerpartner", "kind": "partner"},
        ),
        201,
    )
    stock["own_id"] = stock["owner_id"]
    stock["owner_id"] = partner["id"]
    receipt = await received(client, site, stock, quantity="100")
    contract = body(
        await client.post(
            path(site, "/contracts"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "reason": "Kommissionsvertrag vereinbart",
                "name": "Winzer-Kommission",
                "owner_id": partner["id"],
                "item_id": stock["item_id"],
                "menu_item_id": site.item_id,
                "effective_on": date.today().replace(day=1).isoformat(),
                "stock_per_sale": "1",
                "rules": {
                    "per_sale_cents": 100,
                    "fixed_monthly_cents": 500,
                    "loss_responsibility": "venue",
                    "loss_per_stock_unit_cents": 200,
                },
                **changes,
            },
        ),
        201,
    )
    return {**stock, "contract": contract, "lot_id": receipt["movements"][0]["lot_id"]}


async def paid_order(
    client: AsyncClient, site: Site, workspace: HRWorkspace, quantity: int = 2
) -> tuple[dict, dict]:
    session = await till(client, site, workspace)
    order = await serve(
        client,
        site,
        await sent_order(
            client, site, lines=[{"item_id": site.item_id, "menu_version": 1, "quantity": quantity}]
        ),
    )
    return await payment(client, site, order, session, order["total_cents"]), session


def sale_input(setup: dict, order: dict, **changes: object) -> dict:
    return {
        "request_key": str(uuid.uuid4()),
        "reason": "Bezahlten Partnerverkauf übernehmen",
        "contract_id": setup["contract"]["id"],
        "order_id": order["id"],
        "line_id": order["lines"][0]["line_id"],
        "units": list(range(order["lines"][0]["quantity"])),
        **changes,
    }


async def recognize(
    client: AsyncClient, site: Site, setup: dict, order: dict, **changes: object
) -> dict:
    return body(
        await client.post(
            path(site, "/sales"), headers=site.headers, json=sale_input(setup, order, **changes)
        ),
        201,
    )


async def stock_post(
    client: AsyncClient, site: Site, setup: dict, kind: str, quantity: str
) -> dict:
    return body(
        await client.post(
            path(site, "/stock"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "reason": "Geprüfte Rückgabe oder Bruch",
                "contract_id": setup["contract"]["id"],
                "lot_id": setup["lot_id"],
                "location_id": setup["location_id"],
                "kind": kind,
                "quantity": quantity,
            },
        ),
        201,
    )


async def preview(client: AsyncClient, site: Site, setup: dict, month: date) -> dict:
    return body(
        await client.get(
            path(
                site, f"/contracts/{setup['contract']['id']}/settlement-preview/{month.isoformat()}"
            ),
            headers=site.headers,
        )
    )


async def close(client: AsyncClient, site: Site, setup: dict, month: date) -> dict:
    calculated = await preview(client, site, setup, month)
    payload = {
        "request_key": str(uuid.uuid4()),
        "reason": "Monatsabrechnung geprüft",
        "contract_id": setup["contract"]["id"],
        "month": month.isoformat(),
        "fingerprint": calculated["fingerprint"],
    }
    result = body(
        await client.post(path(site, "/settlements"), headers=site.headers, json=payload), 201
    )
    assert (
        body(
            await client.post(path(site, "/settlements"), headers=site.headers, json=payload), 201
        )["id"]
        == result["id"]
    )
    assert (
        await client.post(
            path(site, "/settlements"),
            headers=site.headers,
            json={**payload, "request_key": str(uuid.uuid4())},
        )
    ).status_code == 409
    return result


@pytest.mark.asyncio
async def test_100_received_30_sold_5_returned_2_broken_leaves_63_with_separate_liability(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    setup = await setup_partner(client, site)
    order, _ = await paid_order(client, site, hr_workspace, 30)
    sales = await recognize(client, site, setup, order)
    assert len(sales["events"]) == 30
    assert len({event["stock_operation_id"] for event in sales["events"]}) == 1
    assert all(event["evidence"] for event in sales["events"])
    returned = await stock_post(client, site, setup, "return", "5")
    broken = await stock_post(client, site, setup, "waste", "2")
    assert returned["events"][0]["gross_cents"] == returned["events"][0]["loss_cents"] == 0
    assert broken["events"][0]["loss_cents"] == 400
    assert (await balances(client, site))[(setup["lot_id"], setup["location_id"])] == Decimal(63)
    calculated = await preview(client, site, setup, date.today().replace(day=1))
    assert calculated["payable_to_partner_cents"] == 3900
    assert calculated["components"][0]["fixed_cents"] == 500


@pytest.mark.asyncio
async def test_partial_payments_cannot_recognize_unpaid_units_then_replay_is_exact(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    setup = await setup_partner(client, site)
    session = await till(client, site, hr_workspace)
    order = await serve(client, site, await sent_order(client, site))
    order = await payment(client, site, order, session, 500)
    payload = sale_input(setup, order)
    assert (
        await client.post(path(site, "/sales"), headers=site.headers, json=payload)
    ).status_code == 409
    order = await payment(client, site, order, session, 1500)
    first = body(await client.post(path(site, "/sales"), headers=site.headers, json=payload), 201)
    replay = body(
        await client.post(
            path(site, "/sales"), headers=site.headers, json={**payload, "units": [1, 0]}
        ),
        201,
    )
    assert replay["id"] == first["id"]
    assert len(first["events"][0]["evidence"]) == 2
    assert (
        await client.post(
            path(site, "/sales"), headers=site.headers, json={**payload, "units": [0]}
        )
    ).status_code == 409
    assert (
        await client.post(path(site, "/sales"), headers=site.headers, json=sale_input(setup, order))
    ).status_code == 409
    assert (await balances(client, site))[(setup["lot_id"], setup["location_id"])] == Decimal(98)


@pytest.mark.asyncio
async def test_decimal_glass_factor_and_partner_ownership_are_exact(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    setup = await setup_partner(client, site, stock_per_sale="0.125")
    own = await received(client, site, {**setup, "owner_id": setup["own_id"]}, quantity="50")
    order, _ = await paid_order(client, site, hr_workspace, 3)
    result = await recognize(client, site, setup, order)
    assert all(Decimal(row["physical_quantity"]) == Decimal("0.125") for row in result["events"])
    physical = await balances(client, site)
    assert physical[(setup["lot_id"], setup["location_id"])] == Decimal("99.625")
    assert physical[(own["movements"][0]["lot_id"], setup["location_id"])] == Decimal(50)


@pytest.mark.asyncio
async def test_quarantine_blocks_partner_sale_without_consuming_own_stock(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    setup = await setup_partner(client, site)
    await received(client, site, {**setup, "owner_id": setup["own_id"]}, quantity="100")
    body(
        await client.post(
            site.path(f"/inventory/lots/{setup['lot_id']}/quarantine"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "reason": "Lieferant hat Charge gesperrt",
                "blocked": True,
                "version": 1,
            },
        ),
        201,
    )
    order, _ = await paid_order(client, site, hr_workspace)
    assert (
        await client.post(path(site, "/sales"), headers=site.headers, json=sale_input(setup, order))
    ).status_code == 409
    assert (await balances(client, site))[(setup["lot_id"], setup["location_id"])] == Decimal(100)
    returned = await stock_post(client, site, setup, "return", "5")
    assert Decimal(returned["events"][0]["physical_quantity"]) == Decimal(5)


@pytest.mark.asyncio
async def test_partner_bears_breakage_and_overdraw_is_rejected(
    client: AsyncClient, site: Site
) -> None:
    setup = await setup_partner(
        client, site, rules={"loss_responsibility": "partner", "loss_per_stock_unit_cents": 10000}
    )
    result = await stock_post(client, site, setup, "waste", "2")
    assert result["events"][0]["loss_cents"] == 0
    assert (
        await client.post(
            path(site, "/stock"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "reason": "Unzulässige Menge",
                "contract_id": setup["contract"]["id"],
                "lot_id": setup["lot_id"],
                "location_id": setup["location_id"],
                "kind": "return",
                "quantity": "99",
            },
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_late_refund_recalculates_original_minimum_and_does_not_restore_goods(
    client: AsyncClient,
    site: Site,
    hr_workspace: HRWorkspace,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    month = date.today().replace(day=1)
    next_period = partners.next_month(month)
    setup = await setup_partner(
        client,
        site,
        rules={
            "revenue_basis": "gross",
            "share_bps": 5000,
            "revenue_threshold_cents": 500,
            "fixed_monthly_cents": 100,
            "minimum_monthly_cents": 500,
        },
    )
    order, session = await paid_order(client, site, hr_workspace)
    await recognize(client, site, setup, order)
    monkeypatch.setattr(partners, "today", lambda venue: next_period)
    first = await close(client, site, setup, month)
    assert first["payable_to_partner_cents"] == 850
    sale_cash = (
        await db_session.execute(
            select(CashEntry).where(
                CashEntry.order_id == uuid.UUID(order["id"]), CashEntry.kind == "sale"
            )
        )
    ).scalar_one()
    # Approval creates a 2000-cent claim; this confirms only the actual
    # 1500-cent partial refund. The remaining claim is not a goods return.
    cancellation = await approve_cancellation(client, site, order, whole=True)
    refund_result = body(
        await client.post(
            site.path(f"/cash/payments/{sale_cash.id}/refunds"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "session_id": session["id"],
                "amount_cents": 1500,
                "cancellation_id": cancellation["id"],
                "confirmed": True,
                "reason": "Begründete Reklamation",
            },
        ),
        201,
    )
    balance = body(
        await client.get(site.path(f"/orders/{order['id']}/balance"), headers=site.headers)
    )
    assert balance["refunded_cents"] == 1500 and balance["refund_due_cents"] == 500
    payload = {
        "request_key": str(uuid.uuid4()),
        "reason": "Bestätigte Rückzahlung übernehmen",
        "contract_id": setup["contract"]["id"],
        "cash_entry_id": refund_result["id"],
    }
    corrected = body(
        await client.post(path(site, "/refunds"), headers=site.headers, json=payload), 201
    )
    assert all(
        row["source_month"] == month.isoformat() and row["posting_month"] == next_period.isoformat()
        for row in corrected["events"]
    )
    assert sum(row["gross_cents"] for row in corrected["events"]) == -1500
    assert all(
        Decimal(row["physical_quantity"]) == 0 and row["stock_operation_id"] is None
        for row in corrected["events"]
    )
    assert (
        body(await client.post(path(site, "/refunds"), headers=site.headers, json=payload), 201)[
            "id"
        ]
        == corrected["id"]
    )
    assert (await balances(client, site))[(setup["lot_id"], setup["location_id"])] == Decimal(98)
    calculated = await preview(client, site, setup, next_period)
    assert (
        calculated["payable_to_partner_cents"] == 150
    )  # current 500 guarantee, original correction -350
    original = next(
        row for row in calculated["components"] if row["source_month"] == month.isoformat()
    )
    assert (
        original["previously_settled_cents"] == 850 and original["calculated_payable_cents"] == 500
    )
    assert (
        await db_session.get(PartnerSettlement, uuid.UUID(first["id"]))
    ).payable_to_partner_cents == 850


@pytest.mark.asyncio
async def test_month_fixed_rent_and_sequential_closure_are_once_only(
    client: AsyncClient, site: Site, monkeypatch: pytest.MonkeyPatch
) -> None:
    month = date.today().replace(day=1)
    setup = await setup_partner(client, site, rules={"fixed_monthly_cents": -500})
    current = await preview(client, site, setup, month)
    assert current["payable_to_partner_cents"] == -500
    assert (
        await client.post(
            path(site, "/settlements"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "reason": "Zu früher Abschluss",
                "contract_id": setup["contract"]["id"],
                "month": month.isoformat(),
                "fingerprint": current["fingerprint"],
            },
        )
    ).status_code == 422
    assert (
        await client.get(
            path(
                site,
                f"/contracts/{setup['contract']['id']}/settlement-preview/{partners.next_month(month)}",
            ),
            headers=site.headers,
        )
    ).status_code == 409
    monkeypatch.setattr(
        partners, "today", lambda venue: partners.next_month(partners.next_month(month))
    )
    assert (await close(client, site, setup, month))["payable_to_partner_cents"] == -500
    assert (await close(client, site, setup, partners.next_month(month)))[
        "payable_to_partner_cents"
    ] == -500


@pytest.mark.asyncio
async def test_terms_are_future_versioned_and_initial_rule_stays_frozen(
    client: AsyncClient, site: Site
) -> None:
    setup = await setup_partner(client, site)
    payload = {
        "request_key": str(uuid.uuid4()),
        "reason": "Neue Monatsbedingungen",
        "expected_version": 1,
        "effective_on": partners.next_month(date.today().replace(day=1)).isoformat(),
        "stock_per_sale": "0.2",
        "rules": {"per_sale_cents": 200},
    }
    endpoint = path(site, f"/contracts/{setup['contract']['id']}/terms")
    result = body(await client.post(endpoint, headers=site.headers, json=payload), 201)
    assert [row["version"] for row in result["terms"]] == [1, 2]
    assert result["terms"][0]["rules"]["per_sale_cents"] == 100
    assert (
        body(await client.post(endpoint, headers=site.headers, json=payload), 201)["terms"]
        == result["terms"]
    )
    assert (
        await client.post(
            endpoint, headers=site.headers, json={**payload, "request_key": str(uuid.uuid4())}
        )
    ).status_code == 409
    assert (
        await client.post(
            endpoint,
            headers=site.headers,
            json={
                **payload,
                "request_key": str(uuid.uuid4()),
                "expected_version": 2,
                "effective_on": date.today().replace(day=1).isoformat(),
            },
        )
    ).status_code == 422


@pytest.mark.asyncio
async def test_roles_and_foreign_venue_ownership_are_rejected(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    setup = await setup_partner(client, site)
    assert (
        await client.get(path(site, "/snapshot"), headers=hr_workspace.headers("worker"))
    ).status_code == 403
    assert (
        await client.get(path(site, "/snapshot"), headers=hr_workspace.headers("other_hr"))
    ).status_code == 404
    foreign_venue = body(
        await client.post("/gastro/venues", headers=site.headers, json={"name": "Anderer Betrieb"}),
        201,
    )
    foreign = Site(foreign_venue["id"], "", "", site.headers)
    assert (
        await client.get(
            path(
                foreign,
                f"/contracts/{setup['contract']['id']}/settlement-preview/{date.today().replace(day=1)}",
            ),
            headers=site.headers,
        )
    ).status_code == 404


@pytest.mark.asyncio
async def test_existing_inventory_loss_is_visible_and_only_financially_recognized_once(
    client: AsyncClient, site: Site
) -> None:
    setup = await setup_partner(client, site)
    loss = body(
        await client.post(
            site.path("/inventory/counts"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "reason": "Zwei Einheiten fehlen in der Inventur",
                "lot_id": setup["lot_id"],
                "location_id": setup["location_id"],
                "expected_quantity": "100",
                "counted_quantity": "98",
            },
        ),
        201,
    )
    pending = body(await client.get(path(site, "/snapshot"), headers=site.headers))[
        "unassigned_losses"
    ]
    assert len(pending) == 1 and pending[0]["stock_operation_id"] == loss["id"]
    payload = {
        "request_key": str(uuid.uuid4()),
        "reason": "Inventurverlust vertraglich zugeordnet",
        "contract_id": setup["contract"]["id"],
        "stock_operation_id": loss["id"],
    }
    first = body(await client.post(path(site, "/losses"), headers=site.headers, json=payload), 201)
    assert first["events"][0]["loss_cents"] == 400
    assert (
        body(await client.post(path(site, "/losses"), headers=site.headers, json=payload), 201)[
            "id"
        ]
        == first["id"]
    )
    assert (
        await client.post(
            path(site, "/losses"),
            headers=site.headers,
            json={**payload, "request_key": str(uuid.uuid4())},
        )
    ).status_code == 409
    assert (await balances(client, site))[(setup["lot_id"], setup["location_id"])] == Decimal(98)
    assert not body(await client.get(path(site, "/snapshot"), headers=site.headers))[
        "unassigned_losses"
    ]


@pytest.mark.asyncio
async def test_sale_candidates_disappear_after_recognition_and_changed_preview_cannot_close(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    month = date.today().replace(day=1)
    setup = await setup_partner(client, site)
    old = await preview(client, site, setup, month)
    order, _ = await paid_order(client, site, hr_workspace)
    candidate_path = path(site, f"/orders/{order['id']}/candidates")
    candidates = body(await client.get(candidate_path, headers=site.headers))
    assert candidates["sales"][0]["units"] == [0, 1]
    assert Decimal(candidates["sales"][0]["stock_quantity"]) == 2
    await recognize(client, site, setup, order)
    assert not body(await client.get(candidate_path, headers=site.headers))["sales"]
    monkeypatch.setattr(partners, "today", lambda venue: partners.next_month(month))
    assert (
        await client.post(
            path(site, "/settlements"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "reason": "Veraltete Vorschau",
                "contract_id": setup["contract"]["id"],
                "month": month.isoformat(),
                "fingerprint": old["fingerprint"],
            },
        )
    ).status_code == 409
    assert (await close(client, site, setup, month))["payable_to_partner_cents"] == 700


@pytest.mark.asyncio
async def test_month_cannot_close_while_proven_partner_sales_are_unrecognized(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, monkeypatch: pytest.MonkeyPatch
) -> None:
    month = date.today().replace(day=1)
    setup = await setup_partner(client, site)
    await paid_order(client, site, hr_workspace)
    calculated = await preview(client, site, setup, month)
    monkeypatch.setattr(partners, "today", lambda venue: partners.next_month(month))
    result = await client.post(
        path(site, "/settlements"),
        headers=site.headers,
        json={
            "request_key": str(uuid.uuid4()),
            "reason": "Noch unvollständiger Monat",
            "contract_id": setup["contract"]["id"],
            "month": month.isoformat(),
            "fingerprint": calculated["fingerprint"],
        },
    )
    assert result.status_code == 409 and "übernehmen" in result.json()["detail"]


async def loan(client: AsyncClient, site: Site, setup: dict, **changes: object) -> dict:
    return body(
        await client.post(
            path(site, "/loans"),
            headers=site.headers,
            json={
                "owner_id": setup["owner_id"],
                "name": "Mehrwegkisten",
                "reference": "CRATES-1",
                "deposit_per_unit_cents": 200,
                **changes,
            },
        ),
        201,
    )


def loan_payload(account: dict, kind: str, **changes: object) -> dict:
    return {
        "request_key": str(uuid.uuid4()),
        "reason": "Leihbestand und Nachweis geprüft",
        "account_id": account["id"],
        "kind": kind,
        **changes,
    }


async def book_loan(
    client: AsyncClient, site: Site, account: dict, kind: str, **changes: object
) -> dict:
    return body(
        await client.post(
            path(site, "/loan-entries"),
            headers=site.headers,
            json=loan_payload(account, kind, **changes),
        ),
        201,
    )


@pytest.mark.asyncio
async def test_loan_custody_and_deposit_claim_are_separate_with_returns_and_loss(
    client: AsyncClient, site: Site
) -> None:
    account = await loan(client, site, await setup_partner(client, site))
    account = await book_loan(client, site, account, "received", quantity=100)
    assert (
        account["physical_quantity"] == 100
        and account["deposit_claim_cents"] == 0
        and account["unpaid_deposit_cents"] == 20000
    )
    account = await book_loan(
        client, site, account, "deposit_paid", amount_cents=20000, external_reference="BANK-PAY-1"
    )
    account = await book_loan(client, site, account, "returned", quantity=30)
    assert (
        account["physical_quantity"] == 70
        and account["deposit_claim_cents"] == 20000
        and account["refundable_deposit_cents"] == 6000
    )
    account = await book_loan(
        client,
        site,
        account,
        "deposit_refunded",
        amount_cents=6000,
        external_reference="BANK-REFUND-1",
    )
    account = await book_loan(client, site, account, "broken", quantity=2)
    account = await book_loan(
        client,
        site,
        account,
        "deposit_forfeited",
        amount_cents=400,
        external_reference="BREAKAGE-1",
    )
    assert (
        account["physical_quantity"] == 68
        and account["deposit_claim_cents"] == 13600
        and account["refundable_deposit_cents"] == 0
    )
    for kind, changes in (
        ("returned", {"quantity": 69}),
        ("deposit_paid", {"amount_cents": 1, "external_reference": "OVERPAY"}),
        ("deposit_refunded", {"amount_cents": 1, "external_reference": "OVERREFUND"}),
        ("deposit_forfeited", {"amount_cents": 1, "external_reference": "OVERLOSS"}),
    ):
        assert (
            await client.post(
                path(site, "/loan-entries"),
                headers=site.headers,
                json=loan_payload(account, kind, **changes),
            )
        ).status_code == 409


@pytest.mark.asyncio
async def test_serialized_asset_cannot_exist_twice_and_payment_proof_is_unique(
    client: AsyncClient, site: Site
) -> None:
    setup = await setup_partner(client, site)
    account = await loan(client, site, setup, serialized=True, reference="SERIAL-COOLER-1")
    assert (
        await client.post(
            path(site, "/loan-entries"),
            headers=site.headers,
            json=loan_payload(account, "received", quantity=2),
        )
    ).status_code == 409
    account = await book_loan(client, site, account, "received", quantity=1)
    assert (
        await client.post(
            path(site, "/loan-entries"),
            headers=site.headers,
            json=loan_payload(account, "received", quantity=1),
        )
    ).status_code == 409
    payload = loan_payload(
        account, "deposit_paid", amount_cents=200, external_reference="ONE-PROOF"
    )
    first = body(
        await client.post(path(site, "/loan-entries"), headers=site.headers, json=payload), 201
    )
    assert (
        body(
            await client.post(path(site, "/loan-entries"), headers=site.headers, json=payload), 201
        )
        == first
    )
    other = await loan(client, site, setup, reference="SERIAL-COOLER-2")
    await book_loan(client, site, other, "received", quantity=1)
    assert (
        await client.post(
            path(site, "/loan-entries"),
            headers=site.headers,
            json={**payload, "account_id": other["id"], "request_key": str(uuid.uuid4())},
        )
    ).status_code == 409


@pytest.mark.asyncio
async def test_concurrent_owner_returns_cannot_overdraw(client: AsyncClient) -> None:
    async with TestSessionLocal() as db:
        tenant = Customer(
            name="Partner concurrency", slug=f"partner-{uuid.uuid4().hex}", status="active"
        )
        db.add(tenant)
        await db.flush()
        user = User(
            email=f"partner-{uuid.uuid4().hex}@example.com",
            hashed_password="unused-fixture",
            full_name="Partner manager",
            role="recruiter",
            tenant_id=tenant.id,
        )
        venue = Venue(name="Concurrent consignments", tenant_id=tenant.id)
        db.add_all([user, venue])
        await db.flush()
        db.add(Membership(venue_id=venue.id, user_id=user.id, role="manager"))
        from app.gastro.station_service import ensure_defaults

        await ensure_defaults(db, venue.id)
        site = Site(str(venue.id), "", "", auth_headers(create_access_token({"sub": user.email})))
        await db.commit()

    async def isolated_db() -> AsyncIterator[AsyncSession]:
        async with TestSessionLocal() as db:
            yield db
            await db.commit()

    original = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = isolated_db
    try:
        menu = body(
            await client.post(
                site.path("/menu"),
                headers=site.headers,
                json={
                    "sku": "CONSIGNED",
                    "data": {"name": "Partnerware", "price_cents": 1000, "tax_rate_bps": 1900},
                },
            ),
            201,
        )
        site.item_id = menu["id"]
        setup = await setup_partner(client, site)
        payload = {
            "reason": "Parallele Eigentümerrückgabe",
            "contract_id": setup["contract"]["id"],
            "lot_id": setup["lot_id"],
            "location_id": setup["location_id"],
            "kind": "return",
            "quantity": "60",
        }
        results = await asyncio.gather(
            *[
                client.post(
                    path(site, "/stock"),
                    headers=site.headers,
                    json={**payload, "request_key": str(uuid.uuid4())},
                )
                for _ in range(2)
            ]
        )
        assert sorted(result.status_code for result in results) == [201, 409]
        assert (await balances(client, site))[(setup["lot_id"], setup["location_id"])] == Decimal(
            40
        )
    finally:
        app.dependency_overrides[get_db] = original


@pytest.mark.asyncio
async def test_partner_migration_round_trip_and_append_only_guards(
    db_session: AsyncSession,
) -> None:
    spec = importlib.util.spec_from_file_location(
        "partner_migration", Path("alembic/versions/073_flintplate_partners.py")
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    connection = await db_session.connection()

    def install(sync: Connection) -> None:
        schema = f"partner_migration_{uuid.uuid4().hex}"
        previous_path = sync.execute(text("SHOW search_path")).scalar_one()
        previous_map = sync.get_execution_options().get("schema_translate_map")
        sync.execution_options(schema_translate_map=None)
        sync.execute(text(f'CREATE SCHEMA "{schema}"'))
        sync.execute(
            text("SELECT set_config('search_path', :path, true)"), {"path": f"{schema},public"}
        )
        try:
            sync.execute(text("CREATE TABLE fp_venues (id uuid PRIMARY KEY)"))
            sync.execute(text("CREATE TABLE users (id uuid PRIMARY KEY)"))
            for name in ("fp_menu_items", "fp_orders", "fp_cash_entries"):
                sync.execute(
                    text(f"CREATE TABLE {name} (id uuid PRIMARY KEY, venue_id uuid NOT NULL)")
                )
            for name in ("fp_stock_items", "fp_stock_owners"):
                sync.execute(
                    text(
                        f"CREATE TABLE {name} (id uuid PRIMARY KEY, venue_id uuid NOT NULL, UNIQUE(venue_id,id))"
                    )
                )
            sync.execute(
                text(
                    "CREATE TABLE fp_stock_operations (id uuid PRIMARY KEY, venue_id uuid NOT NULL, kind text NOT NULL, UNIQUE(venue_id,id), CONSTRAINT ck_fp_stock_operation_kind CHECK(kind IN ('receipt','consume')))"
                )
            )
            with Operations.context(MigrationContext.configure(sync)):
                migration.upgrade()
                migration.downgrade()
                migration.upgrade()
            ids = {
                name: uuid.uuid4()
                for name in (
                    "venue",
                    "user",
                    "owner",
                    "item",
                    "menu",
                    "contract",
                    "terms",
                    "posting",
                    "event",
                    "settlement",
                    "loan",
                    "entry",
                    "key",
                )
            }
            for statement in (
                "INSERT INTO fp_venues VALUES (:venue)",
                "INSERT INTO users VALUES (:user)",
                "INSERT INTO fp_stock_owners VALUES (:owner,:venue)",
                "INSERT INTO fp_stock_items VALUES (:item,:venue)",
                "INSERT INTO fp_menu_items VALUES (:menu,:venue)",
                "INSERT INTO fp_partner_contracts(id,venue_id,owner_id,item_id,menu_item_id,name,currency,request_key,request_hash,actor_id) VALUES (:contract,:venue,:owner,:item,:menu,'Contract','EUR',:key,'hash',:user)",
                "INSERT INTO fp_partner_terms(id,venue_id,contract_id,version,effective_on,active,stock_per_sale,rules,request_key,request_hash,actor_id) VALUES (:terms,:venue,:contract,1,'2026-01-01',true,1,'{}',:key,'hash',:user)",
                "INSERT INTO fp_partner_postings(id,venue_id,contract_id,kind,request_key,request_hash,reason,actor_id) VALUES (:posting,:venue,:contract,'waste',:key,'hash','reason',:user)",
                "INSERT INTO fp_partner_events(id,venue_id,contract_id,terms_id,posting_id,kind,occurred_on,source_month,posting_month,physical_quantity,gross_cents,net_cents,unit_fee_cents,loss_cents,evidence) VALUES (:event,:venue,:contract,:terms,:posting,'waste','2026-01-01','2026-01-01','2026-01-01',1,0,0,0,0,'[]')",
                "INSERT INTO fp_partner_settlements(id,venue_id,contract_id,month,payable_to_partner_cents,snapshot,request_key,request_hash,reason,actor_id) VALUES (:settlement,:venue,:contract,'2026-01-01',0,'{}',:key,'hash','reason',:user)",
                "INSERT INTO fp_loan_accounts(id,venue_id,owner_id,name,reference,serialized,deposit_per_unit_cents,currency) VALUES (:loan,:venue,:owner,'Loan','Ref',false,100,'EUR')",
                "INSERT INTO fp_loan_entries(id,venue_id,account_id,kind,quantity,amount_cents,external_reference,request_key,request_hash,reason,actor_id) VALUES (:entry,:venue,:loan,'received',1,0,'',:key,'hash','reason',:user)",
            ):
                sync.execute(text(statement), ids)
            for table in migration.TABLES:
                for statement in (
                    f"UPDATE {table} SET created_at=now()",
                    f"DELETE FROM {table}",
                    f"TRUNCATE {table} CASCADE",
                ):
                    with pytest.raises(DBAPIError, match="append-only"), sync.begin_nested():
                        sync.execute(text(statement))
        finally:
            sync.execute(
                text("SELECT set_config('search_path', :path, true)"), {"path": previous_path}
            )
            sync.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            sync.execution_options(schema_translate_map=previous_map)

    await connection.run_sync(install)
