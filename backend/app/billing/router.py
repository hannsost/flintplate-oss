"""Billing endpoints – Sprint 2.3.

POST /billing/checkout   – Create Stripe Checkout Session → returns redirect URL
GET  /billing/portal     – Create Stripe Customer Portal Session → returns redirect URL
POST /billing/webhook    – Handle Stripe webhook events (no auth – verified by signature)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.schemas import CheckoutRequest, CheckoutResponse, PortalResponse
from app.billing.service import (
    create_checkout_session,
    create_portal_session,
    handle_stripe_webhook,
)
from app.database import get_db
from app.dependencies import AdminUser

router = APIRouter()


@router.post(
    "/checkout",
    response_model=CheckoutResponse,
    summary="Stripe Checkout-Session erstellen",
)
async def billing_checkout(
    body: CheckoutRequest,
    current_user: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CheckoutResponse:
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kein Tenant zugewiesen.",
        )
    url = await create_checkout_session(db, str(current_user.tenant_id), body.plan)
    return CheckoutResponse(url=url)


@router.get(
    "/portal",
    response_model=PortalResponse,
    summary="Stripe Customer Portal öffnen",
)
async def billing_portal(
    current_user: AdminUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PortalResponse:
    if not current_user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kein Tenant zugewiesen.",
        )
    url = await create_portal_session(db, str(current_user.tenant_id))
    return PortalResponse(url=url)


@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
    summary="Stripe Webhook-Events verarbeiten",
    include_in_schema=False,  # Don't expose in OpenAPI docs
)
async def stripe_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    stripe_signature: Annotated[str | None, Header(alias="stripe-signature")] = None,
) -> dict[str, str]:
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Fehlende Stripe-Signatur.")
    payload = await request.body()
    await handle_stripe_webhook(db, payload, stripe_signature)
    return {"status": "ok"}
