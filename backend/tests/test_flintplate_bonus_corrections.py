"""Bonus corrections preserve original documents, quantities and allocation identity."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import uuid
from collections.abc import AsyncIterator
from datetime import date
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from httpx import AsyncClient
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.database import get_db
from app.gastro.models import Membership, Venue
from app.gastro.purchasing_bonus_state import allocation_digest
from app.gastro.purchasing_terms_schemas import BonusAllocationInput
from app.main import app
from app.security import create_access_token
from app.users.models import User
from tests.conftest import TestSessionLocal
from tests.hr_support import HRWorkspace, body
from tests.test_flintplate import Site
from tests.test_flintplate_purchase_conditions import (
    agreement,
    assert_migrated_orm_columns,
    booking,
    old_invoice,
    state,
)
from tests.test_flintplate_purchasing import catalog, delivered, ordered, path
from tests.utils import auth_headers

pytest_plugins = ["tests.test_flintplate"]


async def prepared(client: AsyncClient, site: Site, *, allocate: bool = True) -> dict:
    setup = await catalog(client, site)
    order = await ordered(client, site, setup)
    await delivered(client, site, setup, order)
    await old_invoice(client, site, setup, order)
    contract = await agreement(client, site, setup)
    await state(client, site, contract)
    document = body(
        await client.post(
            path(site, "/bonus-documents"),
            headers=site.headers,
            json=booking(
                supplier_id=setup["supplier_id"],
                reference="CORRECTION-1",
                issued_on=date.today().isoformat(),
                net_cents=120,
                tax_cents=8,
                currency="EUR",
            ),
        ),
        201,
    )
    allocation_data = booking(
        document_id=document["id"], agreement_id=contract["id"], amount_cents=120
    )
    allocation = (
        body(
            await client.post(
                path(site, "/bonus-allocations"), headers=site.headers, json=allocation_data
            ),
            201,
        )
        if allocate
        else None
    )
    return {
        "stock": setup,
        "document": document,
        "agreement": contract,
        "allocation": allocation,
        "allocation_data": allocation_data,
    }


def corrected(*, version: int = 1, amount: int = 100) -> dict:
    return booking(
        expected_version=version,
        kind="corrected",
        issued_on=date.today().isoformat(),
        net_cents=amount,
        tax_cents=7,
    )


@pytest.mark.asyncio
async def test_reverse_correct_and_reallocate_preserves_full_original_history(
    client: AsyncClient, site: Site
) -> None:
    setup = await prepared(client, site)
    original_stock = body(await client.get(site.path("/inventory/snapshot"), headers=site.headers))
    document_id, allocation_id = setup["document"]["id"], setup["allocation"]["id"]
    endpoint = path(site, f"/bonus-documents/{document_id}/revisions")
    body(
        await client.post(
            endpoint, headers=site.headers, json=booking(expected_version=1, kind="void")
        ),
        409,
    )
    body(await client.post(endpoint, headers=site.headers, json=corrected()), 409)
    reverse_data = booking()
    reverse_path = path(site, f"/bonus-allocations/{allocation_id}/reverse")
    reversal = body(await client.post(reverse_path, headers=site.headers, json=reverse_data), 201)
    repeated = body(await client.post(reverse_path, headers=site.headers, json=reverse_data), 201)
    assert reversal["id"] == repeated["id"] and reversal["amount_cents"] == 120
    body(await client.post(reverse_path, headers=site.headers, json=booking()), 409)
    reopened = body(await client.get(path(site, "/bonuses"), headers=site.headers))
    assert reopened["balances"][0]["remaining_cents"] == 200
    assert reopened["documents"][0]["remaining_cents"] == 120
    revision_data = corrected()
    revision = body(await client.post(endpoint, headers=site.headers, json=revision_data), 201)
    same = body(await client.post(endpoint, headers=site.headers, json=revision_data), 201)
    assert revision["id"] == same["id"] and revision["version"] == 2
    allocation = booking(
        document_id=document_id, agreement_id=setup["agreement"]["id"], amount_cents=100
    )
    body(
        await client.post(path(site, "/bonus-allocations"), headers=site.headers, json=allocation),
        409,
    )
    new_allocation = body(
        await client.post(
            path(site, "/bonus-allocations"),
            headers=site.headers,
            json={**allocation, "document_revision_id": revision["id"]},
        ),
        201,
    )
    assert new_allocation["document_revision_id"] == revision["id"]
    snapshot = body(await client.get(path(site, "/bonuses"), headers=site.headers))
    document = snapshot["documents"][0]
    assert (
        document["version"],
        document["net_cents"],
        document["original_net_cents"],
        document["original_tax_cents"],
    ) == (2, 100, 120, 8)
    assert document["original_issued_on"] == setup["document"]["issued_on"]
    assert document["remaining_cents"] == 0 and snapshot["balances"][0]["remaining_cents"] == 100
    assert len(snapshot["allocations"]) == 2 and len(snapshot["reversals"]) == 1
    assert snapshot["reversals"][0]["allocation_id"] == allocation_id
    legacy_retry = body(
        await client.post(
            path(site, "/bonus-allocations"), headers=site.headers, json=setup["allocation_data"]
        ),
        201,
    )
    assert legacy_retry["id"] == allocation_id
    stock = body(await client.get(site.path("/inventory/snapshot"), headers=site.headers))
    assert stock == original_stock


@pytest.mark.asyncio
async def test_void_and_reactivation_use_versions_and_do_not_erase_original(
    client: AsyncClient, site: Site
) -> None:
    setup = await prepared(client, site, allocate=False)
    endpoint = path(site, f"/bonus-documents/{setup['document']['id']}/revisions")
    void_data = booking(expected_version=1, kind="void")
    void = body(await client.post(endpoint, headers=site.headers, json=void_data), 201)
    snap = body(await client.get(path(site, "/bonuses"), headers=site.headers))
    assert snap["documents"][0]["status"] == "void" and snap["documents"][0]["remaining_cents"] == 0
    body(
        await client.post(
            path(site, "/bonus-allocations"),
            headers=site.headers,
            json={**setup["allocation_data"], "document_revision_id": void["id"]},
        ),
        409,
    )
    body(
        await client.post(
            endpoint, headers=site.headers, json=booking(expected_version=2, kind="void")
        ),
        409,
    )
    body(await client.post(endpoint, headers=site.headers, json=corrected()), 409)
    active = body(await client.post(endpoint, headers=site.headers, json=corrected(version=2)), 201)
    assert active["version"] == 3 and active["previous_revision_id"] == void["id"]
    assert (
        body(await client.post(endpoint, headers=site.headers, json=void_data), 201)["id"]
        == void["id"]
    )
    snap = body(await client.get(path(site, "/bonuses"), headers=site.headers))
    assert snap["documents"][0]["status"] == "active" and snap["documents"][0]["version"] == 3
    assert snap["documents"][0]["original_net_cents"] == 120


@pytest.mark.asyncio
async def test_correction_request_keys_are_bound_to_the_path_and_payload(
    client: AsyncClient, site: Site
) -> None:
    setup = await prepared(client, site)
    data = booking()
    endpoint = path(site, f"/bonus-allocations/{setup['allocation']['id']}/reverse")
    body(await client.post(endpoint, headers=site.headers, json=data), 201)
    body(
        await client.post(
            path(site, f"/bonus-allocations/{uuid.uuid4()}/reverse"),
            headers=site.headers,
            json=data,
        ),
        409,
    )
    body(
        await client.post(
            endpoint, headers=site.headers, json={**data, "reason": "Anderer Vorgang"}
        ),
        409,
    )
    revision_data = corrected()
    body(
        await client.post(
            path(site, f"/bonus-documents/{setup['document']['id']}/revisions"),
            headers=site.headers,
            json=revision_data,
        ),
        201,
    )
    body(
        await client.post(
            path(site, f"/bonus-documents/{uuid.uuid4()}/revisions"),
            headers=site.headers,
            json=revision_data,
        ),
        409,
    )


@pytest.mark.asyncio
async def test_corrections_reject_foreign_venue_or_role_and_incomplete_values(
    client: AsyncClient, site: Site, hr_workspace: HRWorkspace
) -> None:
    setup = await prepared(client, site)
    revision_path = path(site, f"/bonus-documents/{setup['document']['id']}/revisions")
    reversal_path = path(site, f"/bonus-allocations/{setup['allocation']['id']}/reverse")
    body(
        await client.post(reversal_path, headers=hr_workspace.headers("worker"), json=booking()),
        403,
    )
    body(
        await client.post(
            revision_path, headers=hr_workspace.headers("other_hr"), json=corrected()
        ),
        404,
    )
    other = body(
        await client.post(
            "/gastro/venues", headers=site.headers, json={"name": "Andere Korrekturen"}
        ),
        201,
    )
    foreign = Site(other["id"], "", "", site.headers)
    body(
        await client.post(
            path(foreign, f"/bonus-allocations/{setup['allocation']['id']}/reverse"),
            headers=site.headers,
            json=booking(),
        ),
        404,
    )
    body(
        await client.post(
            path(foreign, f"/bonus-documents/{setup['document']['id']}/revisions"),
            headers=site.headers,
            json=corrected(),
        ),
        404,
    )
    body(
        await client.post(
            revision_path,
            headers=site.headers,
            json=booking(expected_version=1, kind="corrected", net_cents=100),
        ),
        422,
    )
    body(
        await client.post(
            revision_path,
            headers=site.headers,
            json=booking(expected_version=1, kind="void", net_cents=100),
        ),
        422,
    )


def test_legacy_allocation_fingerprint_omits_only_the_empty_initial_revision() -> None:
    data = BonusAllocationInput(
        request_key=uuid.uuid4(),
        reason="Legacy allocation",
        document_id=uuid.uuid4(),
        agreement_id=uuid.uuid4(),
        amount_cents=120,
    )
    old = data.model_dump(mode="json")
    old.pop("document_revision_id")
    assert (
        allocation_digest(data)
        == hashlib.sha256(
            json.dumps(old, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    changed = data.model_copy(update={"document_revision_id": uuid.uuid4()})
    assert allocation_digest(changed) != allocation_digest(data)


@pytest.mark.asyncio
async def test_parallel_reversals_and_revisions_have_one_winner(client: AsyncClient) -> None:
    async with TestSessionLocal() as db:
        tenant = Customer(
            name="Bonus corrections", slug=f"correction-{uuid.uuid4().hex}", status="active"
        )
        db.add(tenant)
        await db.flush()
        user = User(
            email=f"correction-{uuid.uuid4().hex}@example.com",
            hashed_password="unused-fixture",
            full_name="Bonus manager",
            role="recruiter",
            tenant_id=tenant.id,
        )
        venue = Venue(name="Concurrent bonus corrections", tenant_id=tenant.id)
        db.add_all([user, venue])
        await db.flush()
        db.add(Membership(venue_id=venue.id, user_id=user.id, role="manager"))
        site = Site(str(venue.id), "", "", auth_headers(create_access_token({"sub": user.email})))
        await db.commit()

    async def isolated_db() -> AsyncIterator[AsyncSession]:
        async with TestSessionLocal() as db:
            yield db
            await db.commit()

    original = app.dependency_overrides[get_db]
    app.dependency_overrides[get_db] = isolated_db
    try:
        setup = await prepared(client, site)
        reverse = path(site, f"/bonus-allocations/{setup['allocation']['id']}/reverse")
        results = await asyncio.gather(
            *(client.post(reverse, headers=site.headers, json=booking()) for _ in range(2))
        )
        assert sorted(row.status_code for row in results) == [201, 409]
        revision = path(site, f"/bonus-documents/{setup['document']['id']}/revisions")
        results = await asyncio.gather(
            *(
                client.post(revision, headers=site.headers, json=corrected(amount=amount))
                for amount in (100, 110)
            )
        )
        assert sorted(row.status_code for row in results) == [201, 409]
        snapshot = body(await client.get(path(site, "/bonuses"), headers=site.headers))
        assert len(snapshot["reversals"]) == len(snapshot["document_revisions"]) == 1
        assert snapshot["documents"][0]["allocated_cents"] == 0
    finally:
        app.dependency_overrides[get_db] = original


@pytest.mark.asyncio
async def test_079_actual_migration_orm_columns_counterdocuments_and_safe_downgrade(
    db_session: AsyncSession,
) -> None:
    migrations = []
    for name in (
        "071_flintplate_purchasing",
        "076a_flintplate_inventory_timestamps",
        "077_flintplate_purchase_conditions",
        "079_flintplate_bonus_corrections",
    ):
        spec = importlib.util.spec_from_file_location(name, Path(f"alembic/versions/{name}.py"))
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        migrations.append(module)
    connection = await db_session.connection()

    def install(sync: Connection) -> None:
        schema = f"bonus_correction_migration_{uuid.uuid4().hex}"
        old_path = sync.execute(text("SHOW search_path")).scalar_one()
        old_map = sync.get_execution_options().get("schema_translate_map")
        sync.execution_options(schema_translate_map=None)
        sync.execute(text(f'CREATE SCHEMA "{schema}"'))
        sync.execute(
            text("SELECT set_config('search_path', :path, true)"), {"path": f"{schema},public"}
        )
        try:
            sync.execute(text("CREATE TABLE fp_venues(id uuid PRIMARY KEY)"))
            sync.execute(text("CREATE TABLE users(id uuid PRIMARY KEY)"))
            for table in (
                "fp_stock_items",
                "fp_stock_owners",
                "fp_stock_locations",
                "fp_stock_operations",
            ):
                sync.execute(
                    text(
                        f"CREATE TABLE {table}(id uuid PRIMARY KEY,venue_id uuid NOT NULL,UNIQUE(venue_id,id))"
                    )
                )
            with Operations.context(MigrationContext.configure(sync)):
                migrations[0].upgrade()
                tables = set(inspect(sync).get_table_names(schema=schema))
                for table in migrations[1].TABLES:
                    if table not in tables:
                        sync.execute(text(f"CREATE TABLE {table}(id uuid PRIMARY KEY)"))
                migrations[1].upgrade()
                migrations[2].upgrade()
            ids = {
                name: uuid.uuid4()
                for name in (
                    "venue",
                    "user",
                    "supplier",
                    "agreement",
                    "document",
                    "allocation",
                    "reversal",
                    "revision",
                    "key",
                )
            }
            for statement in (
                "INSERT INTO fp_venues VALUES (:venue)",
                "INSERT INTO users VALUES (:user)",
                "INSERT INTO fp_suppliers(id,venue_id,name) VALUES (:supplier,:venue,'Correction supplier')",
                "INSERT INTO fp_supplier_bonus_agreements(id,venue_id,supplier_id,reference,period_start,period_end,currency,source_basis,rate_bps,threshold_cents,mode,request_key,request_hash,reason,actor_id) VALUES (:agreement,:venue,:supplier,'BONUS',CURRENT_DATE,CURRENT_DATE,'EUR','own_approved_invoice_net_before_credits',1000,0,'excess_only',:key,'hash','agreement',:user)",
                "INSERT INTO fp_supplier_bonus_documents(id,venue_id,supplier_id,reference,issued_on,net_cents,tax_cents,currency,request_key,request_hash,reason,actor_id) VALUES (:document,:venue,:supplier,'CREDIT',CURRENT_DATE,120,8,'EUR',:key,'hash','document',:user)",
                "INSERT INTO fp_supplier_bonus_allocations(id,venue_id,document_id,agreement_id,amount_cents,request_key,request_hash,reason,actor_id) VALUES (:allocation,:venue,:document,:agreement,120,:key,'legacy-hash','allocation',:user)",
            ):
                sync.execute(text(statement), ids)
            with Operations.context(MigrationContext.configure(sync)):
                migrations[3].upgrade()
                migrations[3].downgrade()
                migrations[3].upgrade()
            assert sync.execute(
                text(
                    "SELECT document_revision_id,request_hash FROM fp_supplier_bonus_allocations WHERE id=:allocation"
                ),
                ids,
            ).one() == (None, "legacy-hash")
            assert_migrated_orm_columns(
                sync,
                schema,
                (
                    "fp_supplier_bonus_document_revisions",
                    "fp_supplier_bonus_allocation_reversals",
                    "fp_supplier_bonus_allocations",
                ),
            )
            sync.execute(
                text(
                    "INSERT INTO fp_supplier_bonus_allocation_reversals(id,venue_id,allocation_id,document_id,agreement_id,amount_cents,request_key,request_hash,reason,actor_id) VALUES (:reversal,:venue,:allocation,:document,:agreement,120,:key,'hash','reversal',:user)"
                ),
                ids,
            )
            sync.execute(
                text(
                    "INSERT INTO fp_supplier_bonus_document_revisions(id,venue_id,document_id,version,kind,issued_on,net_cents,tax_cents,request_key,request_hash,reason,actor_id) VALUES (:revision,:venue,:document,2,'corrected',CURRENT_DATE,100,7,:key,'hash','revision',:user)"
                ),
                ids,
            )
            for table in (
                "fp_supplier_bonus_document_revisions",
                "fp_supplier_bonus_allocation_reversals",
            ):
                for statement in (
                    f"UPDATE {table} SET reason='changed'",
                    f"DELETE FROM {table}",
                    f"TRUNCATE {table} CASCADE",
                ):
                    with pytest.raises(DBAPIError, match="append-only"), sync.begin_nested():
                        sync.execute(text(statement))
            with (
                pytest.raises(DBAPIError, match="would erase"),
                sync.begin_nested(),
                Operations.context(MigrationContext.configure(sync)),
            ):
                migrations[3].downgrade()
            assert (
                sync.execute(
                    text("SELECT net_cents FROM fp_supplier_bonus_documents WHERE id=:document"),
                    ids,
                ).scalar_one()
                == 120
            )
        finally:
            sync.execute(text("SELECT set_config('search_path', :path, true)"), {"path": old_path})
            sync.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            sync.execution_options(schema_translate_map=old_map)

    await connection.run_sync(install)
