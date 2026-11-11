"""Service rounds and the till cooperate without coupling different guests."""

from __future__ import annotations

import uuid

from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from httpx import AsyncClient
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.cash import drawer_balance
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site, serve
from tests.test_flintplate_cash import install_cash_guards, payment, till
from tests.test_flintplate_service_presence import round_for, visit

pytest_plugins = ["tests.test_flintplate"]


async def test_guest_pays_with_tip_while_other_guest_cooks_then_combines_later_rounds(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    current = await visit(client, site, guests=2)
    a, b = current["tabs"]
    round_payload = {
        "request_key": str(uuid.uuid4()),
        "visit_version": current["version"],
        "tab_versions": [{"guest_tab_id": tab["id"], "version": tab["version"]} for tab in (a, b)],
        "rows": [
            {
                "cart_row_id": str(uuid.uuid4()),
                "item_id": site.item_id,
                "menu_version": 1,
                "quantity": 1,
                "assignments": [{"guest_tab_id": tab["id"], "units": [0]}],
            }
            for tab in (a, b)
        ],
    }
    sent = body(
        await client.post(
            site.path(f"/service-visits/{current['id']}/rounds"),
            headers=site.headers,
            json=round_payload,
        ),
        201,
    )
    assert len(sent["children"]) == 2
    children = {child["guest_tab_id"]: child["order"] for child in sent["children"]}
    a_original = children[a["id"]]
    b_original = children[b["id"]]
    a_served = await serve(client, site, a_original)
    session = await till(client, site, hr_workspace)
    quote_input = {
        "scope": {"guest_tab_ids": [a["id"]]},
        "mode": "all",
        "payer_tab_id": a["id"],
        "new_tip_cents": 75,
    }
    quote = body(
        await client.post(
            site.path("/payment-groups/preview"), headers=site.headers, json=quote_input
        )
    )
    assert quote["blockers"] == []
    assert quote["receipt_amount_cents"] == 1000
    assert quote["new_tip_cents"] == 75
    payload = {
        "request_key": str(uuid.uuid4()),
        "quote": quote_input,
        "quote_hash": quote["quote_hash"],
        "session_id": session["id"],
        "received_cents": 1200,
        "confirmed": True,
    }
    first = body(
        await client.post(site.path("/payment-groups/cash"), headers=site.headers, json=payload),
        201,
    )
    assert first["amount_cents"] == 1075 and first["change_cents"] == 125
    assert first["tip_entry_id"]
    assert len(first["entries"]) == 1
    assert first["entries"][0]["order_id"] == a_original["id"]
    assert first["entries"][0]["received_cents"] is None
    assert first["entries"][0]["change_cents"] is None
    assert await drawer_balance(db_session, uuid.UUID(session["id"])) == 6075

    # A's checkout snapshot is frozen. B still advances through its own KDS
    # lifecycle; the common round does not freeze the other original receipt.
    await serve(client, site, b_original)
    a_after = body(await client.get(site.path(f"/orders/{a_original['id']}"), headers=site.headers))
    assert a_after["paid_at"] and a_after["tip_cents"] == 0
    assert a_after["lines"] == a_served["lines"]
    fresh = body(
        await client.get(site.path(f"/service-visits/{current['id']}"), headers=site.headers)
    )
    again = await round_for(client, site, fresh)
    later = again["children"][0]["order"]
    assert later["id"] not in {a_original["id"], b_original["id"]}
    await serve(client, site, later)
    together_input = {
        "scope": {"visit_id": current["id"]},
        "mode": "all",
        "payer_tab_id": a["id"],
    }
    together_quote = body(
        await client.post(
            site.path("/payment-groups/preview"), headers=site.headers, json=together_input
        )
    )
    assert together_quote["blockers"] == []
    assert together_quote["receipt_amount_cents"] == 2000
    assert {row["order_id"] for row in together_quote["allocations"]} == {
        b_original["id"],
        later["id"],
    }
    combined = body(
        await client.post(
            site.path("/payment-groups/cash"),
            headers=site.headers,
            json={
                "request_key": str(uuid.uuid4()),
                "quote": together_input,
                "quote_hash": together_quote["quote_hash"],
                "session_id": session["id"],
                "received_cents": 2500,
                "confirmed": True,
            },
        ),
        201,
    )
    assert len(combined["entries"]) == 2 and combined["change_cents"] == 500
    assert combined["new_tip_cents"] == 0
    assert await drawer_balance(db_session, uuid.UUID(session["id"])) == 8075
    replay = body(
        await client.post(site.path("/payment-groups/cash"), headers=site.headers, json=payload),
        201,
    )
    assert replay == first
    assert await drawer_balance(db_session, uuid.UUID(session["id"])) == 8075


async def test_manager_discount_before_checkout_preserves_guest_original_identity(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace, db_session: AsyncSession
) -> None:
    await install_cash_guards(db_session)
    revision = ScriptDirectory("alembic").get_revision("087")
    assert revision is not None

    def install(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            revision.module.install_guards()

    await (await db_session.connection()).run_sync(install)
    current = await visit(client, site)
    sent = await round_for(client, site, current)
    original = sent["children"][0]["order"]
    discount = {"version": original["version"], "percent": 10, "reason": "  Treuer Gast  "}
    response = await client.post(
        site.path(f"/orders/{original['id']}/discount"),
        headers=hr_workspace.headers("worker"),
        json=discount,
    )
    assert response.status_code == 403
    reduced = body(
        await client.post(
            site.path(f"/orders/{original['id']}/discount"),
            headers=site.headers,
            json=discount,
        )
    )
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    await db_session.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    assert reduced["total_cents"] == 900 and reduced["discount_cents"] == 100
    assert reduced["discount_reason"] == "Treuer Gast"
    for before, after in zip(original["lines"], reduced["lines"], strict=True):
        assert {
            key: value
            for key, value in before.items()
            if key not in {"discount_cents", "total_cents", "tax_cents"}
        } == {
            key: value
            for key, value in after.items()
            if key not in {"discount_cents", "total_cents", "tax_cents"}
        }
    served = await serve(client, site, reduced)
    session = await till(client, site, hr_workspace)
    paid = await payment(client, site, served, session, 900)
    response = await client.post(
        site.path(f"/orders/{original['id']}/discount"),
        headers=site.headers,
        json={**discount, "version": paid["version"], "percent": 20},
    )
    assert response.status_code == 409
    await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
