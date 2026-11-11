"""Side-effect-free supplier calculations shared by purchasing and planning."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel

from app.gastro.purchasing_terms_schemas import ProductConditions, SupplierRules


def request_digest(data: BaseModel) -> str:
    payload = data.model_dump(mode="json")
    # 071 pending payloads did not contain these fields. Preserve their exact hash.
    for field in ("accepted_bonus_quantity", "rejected_bonus_quantity"):
        if field in payload and Decimal(payload[field]) == 0:
            payload.pop(field)
    if payload.get("confirmation_id") is None:
        payload.pop("confirmation_id", None)
    if payload.get("unconfirmed_delivery_reason") == "":
        payload.pop("unconfirmed_delivery_reason", None)
    if payload.get("supplier_terms_id") is None:
        payload.pop("supplier_terms_id", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def priced_packs(packs: int, base_price: int, conditions: ProductConditions) -> tuple[int, int]:
    if packs < conditions.minimum_paid_packs or packs % conditions.order_multiple:
        raise HTTPException(
            422, "Mindestgebinde oder vereinbartes Bestellvielfaches nicht erfüllt."
        )
    if conditions.tiers and conditions.tiers[0].pack_price_cents > base_price:
        raise HTTPException(422, "Eine Mengenstaffel darf den Basispreis nicht übersteigen.")
    price = base_price
    for tier in conditions.tiers:
        if packs >= tier.minimum_paid_packs:
            price = tier.pack_price_cents
    rebate = conditions.natural_rebate
    bonus = packs // rebate.buy_packs * rebate.free_packs if rebate else 0
    return price, bonus


def earliest_delivery(placed_at: datetime, rules: SupplierRules, timezone: str) -> date:
    if placed_at.tzinfo is None:
        raise ValueError("Bestellzeit benötigt einen Zeitzonenbezug.")
    local = placed_at.astimezone(ZoneInfo(timezone))
    start = local.date()
    if rules.order_cutoff_local is not None and local.time() >= rules.order_cutoff_local:
        start += timedelta(days=1)
    candidate = start + timedelta(days=rules.lead_time_calendar_days)
    for _ in range(366):
        if (
            candidate.weekday() in rules.delivery_weekdays
            and candidate not in rules.excluded_delivery_dates
        ):
            return candidate
        candidate += timedelta(days=1)
    raise HTTPException(422, "Im nächsten Jahr ist kein Liefertermin freigegeben.")


def minimum_packs_for_need(
    required: Decimal, pack_quantity: Decimal, conditions: ProductConditions
) -> int:
    if (
        not required.is_finite()
        or required < 0
        or not pack_quantity.is_finite()
        or pack_quantity <= 0
    ):
        raise ValueError("Ungültiger Bedarf oder Gebindeinhalt.")
    if required == 0:
        return 0
    step = conditions.order_multiple
    low, high = (conditions.minimum_paid_packs + step - 1) // step, 1000000 // step

    def supplied(multiples: int) -> Decimal:
        packs = multiples * step
        rebate = conditions.natural_rebate
        bonus = packs // rebate.buy_packs * rebate.free_packs if rebate else 0
        return (packs + bonus) * pack_quantity

    if low > high or supplied(high) < required:
        raise HTTPException(422, "Bedarf überschreitet die maximale Bestellmenge.")
    while low < high:
        middle = (low + high) // 2
        if supplied(middle) >= required:
            high = middle
        else:
            low = middle + 1
    if supplied(low) > 999999999:
        raise HTTPException(422, "Bestellmenge ist zu groß.")
    return low * step


def bonus_claim(net_cents: int, rate_bps: int, threshold_cents: int, mode: str) -> int:
    if mode == "whole_base_at_threshold":
        base = net_cents if net_cents >= threshold_cents else 0
    elif mode == "excess_only":
        base = max(0, net_cents - threshold_cents)
    else:
        raise ValueError("Unbekannte Bonusregel.")
    return int((Decimal(base) * rate_bps / 10000).quantize(Decimal(1), rounding=ROUND_HALF_UP))
