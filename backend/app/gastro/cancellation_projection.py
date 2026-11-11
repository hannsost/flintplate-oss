"""Operational quantities projected from immutable original receipt units."""

from __future__ import annotations

import hashlib
import uuid

from pydantic import JsonValue

from app.gastro.models import Order


def tip_line_id(order_id: uuid.UUID) -> uuid.UUID:
    """Stable synthetic line, reproducible with PostgreSQL's built-in SHA256."""
    return uuid.UUID(hashlib.sha256(f"{order_id}:tip".encode()).hexdigest()[:32])


def line_key(order: Order, index: int, line: dict[str, JsonValue]) -> str:
    return str(line.get("line_id") or uuid.uuid5(order.id, f"line:{index}"))


def remaining_lines(order: Order) -> list[dict[str, JsonValue]]:
    cancelled: dict[str, set[int]] = {}
    for row in order.cancellation_units:
        cancelled.setdefault(str(row.line_id), set()).add(row.unit)
    result: list[dict[str, JsonValue]] = []
    for index, line in enumerate(order.lines):
        key = line_key(order, index, line)
        quantity = int(str(line["quantity"]))
        kept = [unit for unit in range(quantity) if unit not in cancelled.get(key, set())]
        if not kept:
            continue
        gross, tax = int(str(line["total_cents"])), int(str(line["tax_cents"]))
        result.append(
            {
                **line,
                "line_id": key,
                "quantity": len(kept),
                "total_cents": sum(
                    gross * (unit + 1) // quantity - gross * unit // quantity for unit in kept
                ),
                "tax_cents": sum(
                    tax * (unit + 1) // quantity - tax * unit // quantity for unit in kept
                ),
            }
        )
    return result


def update_fulfillment(order: Order) -> None:
    active = remaining_lines(order)
    if not active:
        order.fulfillment_status = "cancelled"
        order.status = "cancelled"
        return
    states = {
        str(line.get("preparation_status", "sent"))
        for line in active
        if line.get("kind", "product") == "product"
    }
    order.fulfillment_status = next(
        (state for state in ("sent", "preparing", "ready", "served") if state in states), "served"
    )
    if order.paid_at is None:
        order.status = order.fulfillment_status
