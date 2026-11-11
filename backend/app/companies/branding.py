"""Self-service branding; tenant identity and platform operator stay separate."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.companies.workspace_access import workspace_admin
from app.database import get_db
from app.security import get_current_user
from app.users.models import User

router = APIRouter(prefix="/workspace")
DB = Annotated[AsyncSession, Depends(get_db)]


class BrandingRead(BaseModel):
    company_name: str
    brand_name: str | None
    slug: str
    primary_color: str
    logo_url: str | None
    version: int
    can_manage: bool


class BrandingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    version: int = Field(ge=1)
    brand_name: str | None = Field(default=None, min_length=1, max_length=80)
    primary_color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    logo_url: str | None = Field(default=None, max_length=500)

    @field_validator("logo_url")
    @classmethod
    def safe_logo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError(
                "Logo-Adresse muss HTTPS verwenden und darf keine Zugangsdaten enthalten."
            )
        return value


def read_branding(customer: Customer, user: User) -> BrandingRead:
    return BrandingRead(
        company_name=customer.name,
        brand_name=customer.brand_name,
        slug=customer.slug,
        primary_color=customer.primary_color or "#2563eb",
        logo_url=customer.logo_url,
        version=customer.branding_version,
        can_manage=user.role == "admin",
    )


async def own_customer(db: AsyncSession, user: User, *, lock: bool = False) -> Customer:
    query = select(Customer).where(Customer.id == user.tenant_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    customer = (await db.execute(query)).scalar_one_or_none()
    if (
        customer is None
        or customer.status not in {"active", "trial"}
        or (
            customer.status == "trial"
            and customer.trial_ends_at
            and customer.trial_ends_at <= datetime.now(UTC)
        )
    ):
        raise HTTPException(403, "Ein aktiver Firmenarbeitsbereich ist erforderlich.")
    return customer


@router.get(
    "/branding",
    response_model=BrandingRead,
    status_code=200,
    summary="Eigenen Markenauftritt laden",
)
async def get_branding(
    user: Annotated[User, Depends(get_current_user)], db: DB, response: Response
) -> BrandingRead:
    response.headers["Cache-Control"] = "no-store"
    return read_branding(await own_customer(db, user), user)


@router.put(
    "/branding",
    response_model=BrandingRead,
    status_code=200,
    summary="Eigenen Markenauftritt speichern",
)
async def update_branding(
    data: BrandingUpdate, user: Annotated[User, Depends(workspace_admin)], db: DB
) -> BrandingRead:
    customer = await own_customer(db, user, lock=True)
    if customer.branding_version != data.version:
        raise HTTPException(409, "Der Markenauftritt wurde geändert. Bitte neu laden und prüfen.")
    customer.brand_name = data.brand_name
    customer.primary_color = data.primary_color.lower()
    customer.logo_url = data.logo_url
    customer.branding_version += 1
    await db.flush()
    return read_branding(customer, user)
