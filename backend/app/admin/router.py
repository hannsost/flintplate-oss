"""Admin Hub – Kunden- und Modulverwaltung.

Endpoints:
  GET    /admin/customers            – Kundenliste mit User-Count + aktive Module
  POST   /admin/customers            – Neuen Kunden anlegen
  GET    /admin/customers/{id}       – Kundendetail
  PATCH  /admin/customers/{id}       – Kundendaten bearbeiten
  DELETE /admin/customers/{id}       – Kunden archivieren (status → churned)

  GET    /admin/customers/{id}/modules      – Modul-Status
  PUT    /admin/customers/{id}/modules/{key}– Modul aktivieren/deaktivieren
  GET    /admin/modules                     – Modul-Katalog

  GET    /admin/stats                        – KPI-Aggregat
  POST   /admin/assign-tenant               – User einem Tenant zuweisen

Alle Endpoints erfordern role=admin.
"""

from __future__ import annotations

import re
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import MODULES, Customer, CustomerModule
from app.admin.schemas import (
    AdminStats,
    AssignTenant,
    CustomerCreate,
    CustomerRead,
    CustomerUpdate,
    ModuleRead,
    ModuleToggle,
    ModuleUsage,
    SetCustomDomain,
)
from app.database import get_db
from app.dependencies import PlatformAdminUser
from app.users.models import User

router = APIRouter()


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _get_customer_or_404(db: AsyncSession, customer_id: uuid.UUID) -> Customer:
    result = await db.execute(select(Customer).where(Customer.id == customer_id))
    c = result.scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=404, detail="Kunde nicht gefunden")
    return c


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[äÄ]", "ae", slug)
    slug = re.sub(r"[öÖ]", "oe", slug)
    slug = re.sub(r"[üÜ]", "ue", slug)
    slug = re.sub(r"[ß]", "ss", slug)
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")[:100]


# ── Customers ─────────────────────────────────────────────────────────────────


@router.get("/customers", response_model=list[CustomerRead], summary="Alle Kunden")
async def list_customers(
    admin: PlatformAdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: str | None = Query(None, alias="status"),
    type_filter: str | None = Query(None, alias="type"),
    limit: int = Query(100, le=500),
    offset: int = 0,
) -> list[CustomerRead]:
    q = select(Customer).order_by(Customer.created_at.desc()).limit(limit).offset(offset)
    if status_filter:
        q = q.where(Customer.status == status_filter)
    if type_filter:
        q = q.where(Customer.type == type_filter)

    result = await db.execute(q)
    customers = result.scalars().all()

    # Fetch user counts per tenant in one query
    counts_result = await db.execute(
        select(User.tenant_id, func.count(User.id))
        .where(User.tenant_id.in_([c.id for c in customers]))
        .group_by(User.tenant_id)
    )
    user_counts = {row[0]: row[1] for row in counts_result}

    # Fetch enabled modules per tenant
    mods_result = await db.execute(
        select(CustomerModule.customer_id, CustomerModule.module_key).where(
            CustomerModule.customer_id.in_([c.id for c in customers]),
            CustomerModule.enabled.is_(True),  # noqa: E712
        )
    )
    mod_map: dict[uuid.UUID, list[str]] = {}
    for cid, key in mods_result:
        mod_map.setdefault(cid, []).append(key)

    out = []
    for c in customers:
        r = CustomerRead.model_validate(c)
        r.user_count = user_counts.get(c.id, 0)
        r.modules = mod_map.get(c.id, [])
        out.append(r)
    return out


@router.post(
    "/customers", response_model=CustomerRead, status_code=201, summary="Neuen Kunden anlegen"
)
async def create_customer(
    body: CustomerCreate,
    admin: PlatformAdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CustomerRead:
    # Check slug uniqueness
    existing = await db.execute(select(Customer).where(Customer.slug == body.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Slug '{body.slug}' bereits vergeben")

    customer = Customer(**body.model_dump())
    db.add(customer)
    await db.flush()

    # Auto-activate default modules based on plan
    default_modules = _default_modules_for_plan(body.plan)
    for key in default_modules:
        db.add(CustomerModule(customer_id=customer.id, module_key=key, enabled=True))

    await db.commit()
    await db.refresh(customer)

    r = CustomerRead.model_validate(customer)
    r.modules = default_modules
    return r


@router.get("/customers/{customer_id}", response_model=CustomerRead, summary="Kundendetail")
async def get_customer(
    customer_id: uuid.UUID,
    admin: PlatformAdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CustomerRead:
    c = await _get_customer_or_404(db, customer_id)

    uc = await db.execute(select(func.count(User.id)).where(User.tenant_id == customer_id))
    user_count = uc.scalar() or 0

    mods = await db.execute(
        select(CustomerModule.module_key).where(
            CustomerModule.customer_id == customer_id, CustomerModule.enabled.is_(True)
        )  # noqa: E712
    )
    modules = [row[0] for row in mods]

    r = CustomerRead.model_validate(c)
    r.user_count = user_count
    r.modules = modules
    return r


@router.patch("/customers/{customer_id}", response_model=CustomerRead, summary="Kunden bearbeiten")
async def update_customer(
    customer_id: uuid.UUID,
    body: CustomerUpdate,
    admin: PlatformAdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CustomerRead:
    c = await _get_customer_or_404(db, customer_id)

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(c, field, value)

    await db.commit()
    await db.refresh(c)
    return CustomerRead.model_validate(c)


@router.delete("/customers/{customer_id}", status_code=204, summary="Kunden archivieren")
async def archive_customer(
    customer_id: uuid.UUID,
    admin: PlatformAdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    c = await _get_customer_or_404(db, customer_id)
    c.status = "churned"
    await db.commit()


# ── Custom Domain (White-Label) ────────────────────────────────────────────────


@router.put(
    "/customers/{customer_id}/custom-domain",
    response_model=CustomerRead,
    summary="Custom-Domain setzen / löschen",
)
async def set_custom_domain(
    customer_id: uuid.UUID,
    body: SetCustomDomain,
    admin: PlatformAdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CustomerRead:
    c = await _get_customer_or_404(db, customer_id)

    domain = body.custom_domain.lower().strip() if body.custom_domain else None

    # Uniqueness check (allow setting same domain on same customer)
    if domain:
        conflict = await db.execute(
            select(Customer.id).where(
                Customer.custom_domain == domain,
                Customer.id != customer_id,
            )
        )
        if conflict.scalar_one_or_none():
            raise HTTPException(
                status_code=409,
                detail=f"Domain '{domain}' ist bereits einem anderen Kunden zugewiesen",
            )

    old_domain = c.custom_domain
    c.custom_domain = domain

    # Invalidate Redis cache for old and new domain
    try:
        from app.cache import redis_client

        async with redis_client() as cache:
            for changed_domain in {old_domain, domain} - {None, ""}:
                await cache.delete(f"custom_domain:{changed_domain}")
    except Exception:
        pass

    await db.commit()
    await db.refresh(c)
    return CustomerRead.model_validate(c)


# ── Logo Upload / Branding (Sprint 2.8) ───────────────────────────────────────


class LogoPresignResponse(BaseModel):
    upload_url: str
    logo_url: str
    expires_in: int = 300


class BrandingUpdate(BaseModel):
    primary_color: str | None = None  # hex e.g. "#2563eb", None = keep current
    logo_url: str | None = None  # set after upload; "__clear__" = remove


@router.post(
    "/customers/{customer_id}/logo-presign",
    response_model=LogoPresignResponse,
    summary="Presigned PUT-URL für Logo-Upload generieren",
)
async def get_logo_upload_url(
    customer_id: uuid.UUID,
    admin: PlatformAdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    content_type: str = Query("image/png", description="MIME-Type der Datei"),
) -> LogoPresignResponse:
    await _get_customer_or_404(db, customer_id)
    from app.storage.s3 import StorageNotConfigured, generate_presigned_upload

    try:
        upload_url, logo_url = await generate_presigned_upload(
            tenant_id=str(customer_id),
            filename="logo",
            content_type=content_type,
        )
    except StorageNotConfigured:
        raise HTTPException(
            status_code=503,
            detail="S3/R2 Storage nicht konfiguriert. Bitte Logo-URL manuell eintragen.",
        ) from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return LogoPresignResponse(upload_url=upload_url, logo_url=logo_url)


@router.patch(
    "/customers/{customer_id}/branding",
    response_model=CustomerRead,
    summary="Logo-URL und Primärfarbe setzen",
)
async def update_branding(
    customer_id: uuid.UUID,
    body: BrandingUpdate,
    admin: PlatformAdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CustomerRead:
    c = await db.scalar(
        select(Customer)
        .where(Customer.id == customer_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if c is None:
        raise HTTPException(404, "Kunde nicht gefunden.")

    if body.primary_color is not None:
        # Validate hex color
        import re as _re

        if not _re.match(r"^#[0-9a-fA-F]{6}$", body.primary_color):
            raise HTTPException(
                status_code=400,
                detail="primary_color muss ein gültiger Hex-Farbcode sein (#rrggbb)",
            )
        c.primary_color = body.primary_color

    if body.logo_url is not None:
        c.logo_url = None if body.logo_url == "__clear__" else body.logo_url

    c.branding_version += 1
    await db.commit()
    await db.refresh(c)
    return CustomerRead.model_validate(c)


# ── Modules ────────────────────────────────────────────────────────────────────


@router.get("/modules", summary="Modul-Katalog")
async def list_modules(admin: PlatformAdminUser) -> list[dict[str, Any]]:
    return MODULES


@router.get(
    "/customers/{customer_id}/modules",
    response_model=list[ModuleRead],
    summary="Module eines Kunden",
)
async def get_customer_modules(
    customer_id: uuid.UUID,
    admin: PlatformAdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[ModuleRead]:
    await _get_customer_or_404(db, customer_id)
    result = await db.execute(
        select(CustomerModule)
        .where(CustomerModule.customer_id == customer_id)
        .order_by(CustomerModule.module_key)
    )
    return [ModuleRead.model_validate(module) for module in result.scalars()]


@router.put(
    "/customers/{customer_id}/modules/{module_key}",
    response_model=ModuleRead,
    summary="Modul aktivieren / deaktivieren",
)
async def toggle_module(
    customer_id: uuid.UUID,
    module_key: str,
    body: ModuleToggle,
    admin: PlatformAdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ModuleRead:
    await _get_customer_or_404(db, customer_id)

    # Validate module key
    valid_keys = {m["key"] for m in MODULES}
    if module_key not in valid_keys:
        raise HTTPException(status_code=400, detail=f"Unbekannter Modul-Key: {module_key}")

    result = await db.execute(
        select(CustomerModule).where(
            CustomerModule.customer_id == customer_id,
            CustomerModule.module_key == module_key,
        )
    )
    cm = result.scalar_one_or_none()

    if cm is None:
        cm = CustomerModule(
            customer_id=customer_id,
            module_key=module_key,
            enabled=body.enabled,
            usage_limit=body.usage_limit,
            expires_at=body.expires_at,
        )
        db.add(cm)
    else:
        cm.enabled = body.enabled
        if body.usage_limit is not None:
            cm.usage_limit = body.usage_limit
        if body.expires_at is not None:
            cm.expires_at = body.expires_at

    await db.commit()
    await db.refresh(cm)
    return ModuleRead.model_validate(cm)


# ── Stats ──────────────────────────────────────────────────────────────────────


@router.get("/stats", response_model=AdminStats, summary="Admin KPIs")
async def get_stats(
    admin: PlatformAdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AdminStats:
    # Total / by status
    total_res = await db.execute(select(func.count(Customer.id)))
    total = total_res.scalar() or 0

    status_res = await db.execute(
        select(Customer.status, func.count(Customer.id)).group_by(Customer.status)
    )
    by_status = {row[0]: row[1] for row in status_res}

    # By type
    type_res = await db.execute(
        select(Customer.type, func.count(Customer.id)).group_by(Customer.type)
    )
    by_type = {row[0]: row[1] for row in type_res}

    # By plan
    plan_res = await db.execute(
        select(Customer.plan, func.count(Customer.id)).group_by(Customer.plan)
    )
    by_plan = {row[0]: row[1] for row in plan_res}

    # Top enabled modules
    mod_res = await db.execute(
        select(CustomerModule.module_key, func.count(CustomerModule.id))
        .where(CustomerModule.enabled.is_(True))  # noqa: E712
        .group_by(CustomerModule.module_key)
        .order_by(func.count(CustomerModule.id).desc())
        .limit(10)
    )
    top_modules = [ModuleUsage(module_key=row[0], count=row[1]) for row in mod_res]

    return AdminStats(
        total_customers=total,
        active_customers=by_status.get("active", 0),
        trial_customers=by_status.get("trial", 0),
        suspended_customers=by_status.get("suspended", 0),
        by_type=by_type,
        by_plan=by_plan,
        top_modules=top_modules,
    )


# ── Assign user to tenant ──────────────────────────────────────────────────────


@router.post("/assign-tenant", status_code=204, summary="User einem Tenant zuweisen")
async def assign_tenant(
    body: AssignTenant,
    admin: PlatformAdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    result = await db.execute(select(User).where(User.id == body.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User nicht gefunden")

    if body.tenant_id is not None:
        # Validate tenant exists
        tenant_check = await db.execute(select(Customer.id).where(Customer.id == body.tenant_id))
        if not tenant_check.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Tenant nicht gefunden")

    user.tenant_id = body.tenant_id
    await db.commit()


# ── Job Import Runs ────────────────────────────────────────────────────────────


class TriggerImportRequest(BaseModel):
    source: str = "all"  # "all" | "mock" | "bundesagentur" | rss source key


@router.get(
    "/import-runs",
    summary="Letzte Job-Import-Runs abrufen",
)
async def list_import_runs(
    admin: PlatformAdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(50, le=200),
) -> list[dict[str, Any]]:
    from app.jobs.models_import import JobImportRun

    result = await db.execute(
        select(JobImportRun).order_by(JobImportRun.started_at.desc()).limit(limit)
    )
    runs = result.scalars().all()
    return [
        {
            "id": str(r.id),
            "source": r.source,
            "status": r.status,
            "jobs_found": r.jobs_found,
            "jobs_new": r.jobs_new,
            "error_msg": r.error_msg,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in runs
    ]


@router.post(
    "/import-runs",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Job-Import manuell auslösen",
)
async def trigger_import(
    body: TriggerImportRequest,
    admin: PlatformAdminUser,
) -> dict[str, str]:
    """Triggers an async import run. Returns immediately."""
    import asyncio

    from app.jobs.import_runner import run_all, run_and_log

    async def _run() -> None:
        if body.source == "all":
            await run_all()
        else:
            await run_and_log(body.source)

    asyncio.ensure_future(_run())
    return {"status": "triggered", "source": body.source}


# ── Helpers ────────────────────────────────────────────────────────────────────


def _default_modules_for_plan(plan: str) -> list[str]:
    """Return module keys auto-enabled for a given plan."""
    base = ["kanban_pipeline", "interview_scheduling"]
    if plan in ("starter", "professional", "enterprise"):
        base += ["ai_cv_parser", "ai_cover_letter", "analytics_advanced"]
    if plan in ("professional", "enterprise"):
        base += ["ai_interview_prep", "ai_linkedin_post", "content_kit", "map_view"]
    if plan == "enterprise":
        base += ["zeitarbeit_pool", "partner_portal", "job_scraper_import"]
    return base
