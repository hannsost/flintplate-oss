"""Exercise the installed Stripe SDK with signed local events and mocked HTTP calls."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import Mock

import pytest
import stripe
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import Customer
from app.billing import service
from app.config import get_settings
from tests.hr_support import HRWorkspace, body

WEBHOOK_SECRET = "whsec_synthetic_local_test"


@pytest.fixture(autouse=True)
def stripe_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings().model_copy(
        update={
            "stripe_secret_key": "sk_test_synthetic_local_only",
            "stripe_webhook_secret": WEBHOOK_SECRET,
            "stripe_price_starter": "price_synthetic_starter",
            "stripe_price_professional": "price_synthetic_pro",
        }
    )
    monkeypatch.setattr(service, "_settings", lambda: settings)
    monkeypatch.setattr(service, "_price_to_plan", {})
    monkeypatch.setattr(stripe, "api_key", "sk_test_synthetic_local_only")


async def event(client: AsyncClient, type_: str, data: dict) -> dict:
    payload = json.dumps(
        {"id": "evt_synthetic", "object": "event", "type": type_, "data": {"object": data}}
    ).encode()
    stamp = int(time.time())
    signature = hmac.new(
        WEBHOOK_SECRET.encode(), str(stamp).encode() + b"." + payload, hashlib.sha256
    ).hexdigest()
    return body(
        await client.post(
            "/billing/webhook",
            content=payload,
            headers={"stripe-signature": f"t={stamp},v1={signature}"},
        )
    )


async def test_checkout_subscription_changes_and_cancellation(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = hr_workspace
    tenant_id = h.hr.tenant_id
    subscription = {
        "id": "sub_synthetic",
        "status": "active",
        "items": {"data": [{"price": {"id": "price_synthetic_starter"}}]},
    }
    retrieve = Mock(return_value=stripe.Subscription.construct_from(subscription, "sk_test_unused"))
    monkeypatch.setattr(stripe.Subscription, "retrieve", retrieve)
    await event(
        client,
        "checkout.session.completed",
        {
            "metadata": {"tenant_id": str(tenant_id)},
            "customer": "cus_synthetic",
            "subscription": "sub_synthetic",
        },
    )
    customer = await db_session.get(Customer, tenant_id)
    assert customer is not None
    assert customer.plan == "starter" and customer.status == "active"
    assert customer.stripe_customer_id == "cus_synthetic"
    retrieve.assert_called_once_with("sub_synthetic", expand=["items.data.price"])
    subscription["items"] = {"data": [{"price": {"id": "price_synthetic_pro"}}]}
    for status, expected in [
        ("active", "active"),
        ("past_due", "suspended"),
        ("unpaid", "suspended"),
    ]:
        subscription["status"] = status
        await event(client, "customer.subscription.updated", subscription)
        await db_session.refresh(customer)
        assert customer.plan == "professional" and customer.status == expected
    await event(client, "customer.subscription.deleted", subscription)
    await db_session.refresh(customer)
    assert customer.plan == "free" and customer.status == "churned"
    assert customer.stripe_subscription_id is None
    await event(client, "customer.subscription.deleted", subscription)
    foreign = await db_session.get(Customer, h.other_hr.tenant_id)
    assert foreign is not None and foreign.status == "active"


@pytest.mark.parametrize("payload", [b"{}", b"not json"])
async def test_invalid_webhook_signatures_change_nothing(
    client: AsyncClient, payload: bytes
) -> None:
    response = await client.post(
        "/billing/webhook", content=payload, headers={"stripe-signature": "t=1,v1=invalid"}
    )
    assert response.status_code == 400
    assert (await client.post("/billing/webhook", content=payload)).status_code == 400


async def test_checkout_and_customer_portal_use_company_identifiers(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = hr_workspace
    h.hr.role = "admin"
    customer = await db_session.get(Customer, h.hr.tenant_id)
    assert customer is not None
    customer.stripe_customer_id = "cus_synthetic"
    await db_session.flush()
    checkout = Mock(
        return_value=stripe.checkout.Session.construct_from(
            {"url": "https://checkout.stripe.com/synthetic"}, "sk_test_unused"
        )
    )
    portal = Mock(
        return_value=stripe.billing_portal.Session.construct_from(
            {"url": "https://billing.stripe.com/synthetic"}, "sk_test_unused"
        )
    )
    monkeypatch.setattr(stripe.checkout.Session, "create", checkout)
    monkeypatch.setattr(stripe.billing_portal.Session, "create", portal)
    assert (
        body(await client.post("/billing/checkout", headers=h.headers(), json={"plan": "starter"}))[
            "url"
        ]
        == "https://checkout.stripe.com/synthetic"
    )
    assert checkout.call_args.kwargs["customer"] == "cus_synthetic"
    assert checkout.call_args.kwargs["metadata"]["tenant_id"] == str(customer.id)
    assert (
        body(await client.get("/billing/portal", headers=h.headers()))["url"]
        == "https://billing.stripe.com/synthetic"
    )
    assert portal.call_args.kwargs["customer"] == "cus_synthetic"


@pytest.mark.parametrize("failure", ["provider", "empty_url"])
async def test_checkout_provider_errors_are_actionable(
    client: AsyncClient,
    db_session: AsyncSession,
    hr_workspace: HRWorkspace,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    h = hr_workspace
    h.hr.role = "admin"
    await db_session.flush()
    checkout = (
        Mock(side_effect=stripe.APIConnectionError("private provider diagnostics"))
        if failure == "provider"
        else Mock(
            return_value=stripe.checkout.Session.construct_from({"url": None}, "sk_test_unused")
        )
    )
    monkeypatch.setattr(stripe.checkout.Session, "create", checkout)
    response = await client.post("/billing/checkout", headers=h.headers(), json={"plan": "starter"})
    assert response.status_code == 502
    assert "private provider diagnostics" not in response.text
