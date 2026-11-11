"""Billing schemas – Sprint 2.3."""

from __future__ import annotations

from pydantic import BaseModel


class CheckoutRequest(BaseModel):
    plan: str  # "starter" | "professional" | "enterprise"


class CheckoutResponse(BaseModel):
    url: str  # Stripe Checkout redirect URL


class PortalResponse(BaseModel):
    url: str  # Stripe Customer Portal URL
