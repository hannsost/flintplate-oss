"""Stripe billing service – Sprint 2.3.

Env vars required (all optional – feature disabled if absent):
  STRIPE_SECRET_KEY          – sk_live_... or sk_test_...
  STRIPE_WEBHOOK_SECRET      – whsec_...
  STRIPE_PRICE_STARTER       – price_xxx
  STRIPE_PRICE_PROFESSIONAL  – price_xxx
  STRIPE_PRICE_ENTERPRISE    – price_xxx
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import stripe
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings

log = logging.getLogger(__name__)

# Map plan name → config attribute holding the Stripe Price ID
_PLAN_PRICE_ATTR: dict[str, str] = {
    "starter": "stripe_price_starter",
    "professional": "stripe_price_professional",
    "enterprise": "stripe_price_enterprise",
}

# Map Stripe Price ID → plan name (built lazily on first webhook call)
_price_to_plan: dict[str, str] = {}


def _settings() -> Settings:
    from app.config import get_settings

    return get_settings()


def _get_price_id(plan: str) -> str:
    s = _settings()
    attr = _PLAN_PRICE_ATTR.get(plan)
    if not attr:
        raise HTTPException(status_code=400, detail=f"Unbekannter Plan: {plan}")
    price_id: str | None = getattr(s, attr, None)
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Stripe Price-ID für Plan '{plan}' nicht konfiguriert.",
        )
    return price_id


def _build_price_map() -> None:
    """Populate _price_to_plan reverse lookup from settings."""
    s = _settings()
    for plan, attr in _PLAN_PRICE_ATTR.items():
        pid: str | None = getattr(s, attr, None)
        if pid:
            _price_to_plan[pid] = plan


async def create_checkout_session(
    db: AsyncSession,
    tenant_id: str,
    plan: str,
) -> str:
    """Create a Stripe Checkout Session and return the redirect URL."""
    s = _settings()
    if not s.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe-Integration nicht konfiguriert.",
        )

    price_id = _get_price_id(plan)

    from app.admin.models import Customer

    result = await db.execute(select(Customer).where(Customer.id == tenant_id))
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Tenant nicht gefunden.")

    def _create() -> str:
        stripe.api_key = s.stripe_secret_key
        params: dict[str, Any] = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": f"{s.frontend_url}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            "cancel_url": f"{s.frontend_url}/billing/cancel",
            "metadata": {"tenant_id": str(tenant_id)},
            "allow_promotion_codes": True,
        }
        if customer.stripe_customer_id:
            params["customer"] = customer.stripe_customer_id
        elif customer.contact_email:
            params["customer_email"] = customer.contact_email

        session = stripe.checkout.Session.create(**params)
        url = session.url
        if not isinstance(url, str) or not url:
            raise HTTPException(
                status_code=502, detail="Zahlungsanbieter hat keinen gültigen Link geliefert."
            )
        return url

    try:
        return await asyncio.to_thread(_create)
    except stripe.StripeError:
        raise HTTPException(
            status_code=502, detail="Zahlungsanbieter derzeit nicht erreichbar."
        ) from None


async def create_portal_session(
    db: AsyncSession,
    tenant_id: str,
) -> str:
    """Create a Stripe Customer Portal session and return the redirect URL."""
    s = _settings()
    if not s.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe-Integration nicht konfiguriert.",
        )

    from app.admin.models import Customer

    result = await db.execute(select(Customer).where(Customer.id == tenant_id))
    customer = result.scalar_one_or_none()
    stripe_customer_id = customer.stripe_customer_id if customer else None
    if not stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Kein Stripe-Kunde vorhanden. Bitte zuerst ein Abonnement abschließen.",
        )

    def _create() -> str:
        stripe.api_key = s.stripe_secret_key
        session = stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=f"{s.frontend_url}/dashboard/plan",
        )
        url = session.url
        if not isinstance(url, str) or not url:
            raise HTTPException(
                status_code=502, detail="Zahlungsanbieter hat keinen gültigen Link geliefert."
            )
        return url

    try:
        return await asyncio.to_thread(_create)
    except stripe.StripeError:
        raise HTTPException(
            status_code=502, detail="Zahlungsanbieter derzeit nicht erreichbar."
        ) from None


async def handle_stripe_webhook(db: AsyncSession, payload: bytes, sig_header: str) -> None:
    """Verify and process a Stripe webhook event."""
    s = _settings()
    if not s.stripe_secret_key or not s.stripe_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe-Webhook nicht konfiguriert.",
        )

    stripe.api_key = s.stripe_secret_key

    def _construct() -> stripe.Event:
        event = stripe.Webhook.construct_event(payload, sig_header, s.stripe_webhook_secret)
        if not isinstance(event, stripe.Event):
            raise ValueError("Unexpected Stripe event representation")
        return event

    try:
        event = await asyncio.to_thread(_construct)
    except stripe.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Ungültige Webhook-Signatur.") from None
    except ValueError:
        raise HTTPException(status_code=400, detail="Ungültige Webhook-Daten.") from None

    event_data = event.to_dict()
    event_type: str = event_data["type"]
    data = event_data["data"]["object"]

    if event_type == "checkout.session.completed":
        await _on_checkout_completed(db, data)
    elif event_type in ("customer.subscription.updated", "customer.subscription.created"):
        await _on_subscription_updated(db, data)
    elif event_type == "customer.subscription.deleted":
        await _on_subscription_deleted(db, data)


async def _on_checkout_completed(db: AsyncSession, session: dict[str, Any]) -> None:
    tenant_id: str | None = (session.get("metadata") or {}).get("tenant_id")
    if not tenant_id:
        return

    stripe_customer_id: str | None = session.get("customer")
    stripe_subscription_id: str | None = session.get("subscription")

    from app.admin.models import Customer

    result = await db.execute(select(Customer).where(Customer.id == tenant_id))
    customer = result.scalar_one_or_none()
    if not customer:
        return

    if stripe_customer_id:
        customer.stripe_customer_id = stripe_customer_id
    if stripe_subscription_id:
        customer.stripe_subscription_id = stripe_subscription_id
        # Determine plan from subscription price
        plan = await asyncio.to_thread(
            _get_plan_from_subscription, stripe_customer_id or "", stripe_subscription_id
        )
        if plan:
            customer.plan = plan
    customer.status = "active"
    await db.commit()
    log.info("Checkout completed: tenant=%s plan=%s", tenant_id, customer.plan)


async def _on_subscription_updated(db: AsyncSession, subscription: dict[str, Any]) -> None:
    stripe_sub_id: str = subscription.get("id", "")
    if not stripe_sub_id:
        return

    from app.admin.models import Customer

    result = await db.execute(
        select(Customer).where(Customer.stripe_subscription_id == stripe_sub_id)
    )
    customer = result.scalar_one_or_none()
    if not customer:
        return

    plan = _plan_from_subscription_data(subscription)
    if plan:
        customer.plan = plan
    sub_status: str = subscription.get("status", "")
    if sub_status == "active":
        customer.status = "active"
    elif sub_status in ("past_due", "unpaid"):
        customer.status = "suspended"
    await db.commit()
    log.info("Subscription updated: tenant=%s plan=%s", customer.id, customer.plan)


async def _on_subscription_deleted(db: AsyncSession, subscription: dict[str, Any]) -> None:
    stripe_sub_id: str = subscription.get("id", "")
    from app.admin.models import Customer

    result = await db.execute(
        select(Customer).where(Customer.stripe_subscription_id == stripe_sub_id)
    )
    customer = result.scalar_one_or_none()
    if not customer:
        return

    customer.plan = "free"
    customer.status = "churned"
    customer.stripe_subscription_id = None
    await db.commit()
    log.info("Subscription cancelled: tenant=%s", customer.id)


def _plan_from_subscription_data(subscription: dict[str, Any]) -> str | None:
    """Extract plan name from subscription line item price ID."""
    if not _price_to_plan:
        _build_price_map()
    items = (subscription.get("items") or {}).get("data", [])
    for item in items:
        price_id = (item.get("price") or {}).get("id")
        if price_id and price_id in _price_to_plan:
            return _price_to_plan[price_id]
    return None


def _get_plan_from_subscription(stripe_customer_id: str, subscription_id: str) -> str | None:
    """Fetch subscription from Stripe and determine plan. Runs in thread."""
    try:
        stripe.api_key = _settings().stripe_secret_key
        sub = stripe.Subscription.retrieve(subscription_id, expand=["items.data.price"])
        return _plan_from_subscription_data(sub.to_dict())
    except stripe.StripeError:
        log.warning("Could not determine plan from subscription %s", subscription_id)
        return None
