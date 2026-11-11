"""Reconstruct evidenced moving lot costs without changing any stock ledger entry."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro.inventory_models import (
    StockItem,
    StockLot,
    StockMovement,
    StockOperation,
    StockOwner,
)
from app.gastro.purchasing_models import PurchaseOrderLine, PurchaseReceipt

ZERO = Decimal(0)


def cents(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


@dataclass
class CostPool:
    quantity: Decimal = ZERO
    known_quantity: Decimal = ZERO
    known_value: Decimal = ZERO

    def add(self, quantity: Decimal, value: Decimal | None, *, fully_valued: bool = True) -> None:
        self.quantity += quantity
        if value is not None:
            if fully_valued:
                self.known_quantity += quantity
            self.known_value += value

    def take(self, quantity: Decimal) -> tuple[Decimal, Decimal]:
        """Mixed known/unknown receipts deplete proportionally, never at a future price."""
        if quantity <= 0:
            raise ValueError("Consumption must be positive")
        if self.quantity < quantity:
            # A corrupt/incomplete legacy ledger is not a zero-cost receipt.
            self.add(quantity - self.quantity, None)
        fraction = quantity / self.quantity
        known_quantity = (
            quantity if self.known_quantity == self.quantity else self.known_quantity * fraction
        )
        value = self.known_value * fraction
        self.quantity -= quantity
        self.known_quantity -= known_quantity
        self.known_value -= value
        return value, max(ZERO, quantity - known_quantity)


class StockUsage(BaseModel):
    item_id: uuid.UUID
    name: str
    unit: str
    consumed_quantity: Decimal = ZERO
    waste_quantity: Decimal = ZERO
    count_delta: Decimal = ZERO
    production_input_quantity: Decimal = ZERO
    known_consumption_cost_cents: int = 0
    unvalued_consumption_quantity: Decimal = ZERO
    known_waste_cost_cents: int = 0
    unvalued_waste_quantity: Decimal = ZERO


@dataclass
class StockCosts:
    usage: list[StockUsage]
    line_costs: dict[tuple[str, str], int | None]


async def stock_costs(
    db: AsyncSession, venue_id: uuid.UUID, start: datetime, as_of: datetime
) -> StockCosts:
    movements = (
        await db.execute(
            select(StockMovement, StockOperation, StockLot, StockItem)
            .join(StockOperation, StockOperation.id == StockMovement.operation_id)
            .join(StockLot, StockLot.id == StockMovement.lot_id)
            .join(StockItem, StockItem.id == StockLot.item_id)
            .join(StockOwner, StockOwner.id == StockLot.owner_id)
            .where(
                StockMovement.venue_id == venue_id,
                StockOwner.kind == "own",
                StockOperation.created_at <= as_of,
            )
            .order_by(StockOperation.sequence, StockMovement.id)
        )
    ).all()
    receipts = (
        await db.execute(
            select(PurchaseReceipt, PurchaseOrderLine)
            .join(PurchaseOrderLine, PurchaseOrderLine.id == PurchaseReceipt.line_id)
            .where(
                PurchaseReceipt.venue_id == venue_id,
                PurchaseReceipt.stock_operation_id.is_not(None),
            )
        )
    ).all()
    receipt_values = {
        receipt.stock_operation_id: (
            (receipt.accepted_quantity - receipt.accepted_bonus_quantity)
            * line.pack_price_cents
            / line.pack_quantity
        )
        for receipt, line in receipts
    }
    pools: dict[uuid.UUID, CostPool] = defaultdict(CostPool)
    usage: dict[uuid.UUID, StockUsage] = {}
    consumed_values: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    waste_values: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    line_values: dict[tuple[str, str], Decimal | None] = {}
    grouped: dict[uuid.UUID, list[tuple[StockMovement, StockOperation, StockLot, StockItem]]] = (
        defaultdict(list)
    )
    for movement, operation, lot, item in movements:
        grouped[operation.id].append((movement, operation, lot, item))
    for entries in grouped.values():
        operation = entries[0][1]
        if operation.kind in {"transfer", "quarantine"}:
            continue
        in_window = operation.created_at >= start
        input_value, unknown_input = ZERO, False
        key = (str(operation.details.get("order_id")), str(operation.details.get("line_id")))
        linked_sale = operation.kind == "consume" and key[0] != "None" and key[1] != "None"
        # Every source cost is consumed before a produced lot receives its value.
        for movement, _, lot, item in entries:
            row = usage.setdefault(
                item.id, StockUsage(item_id=item.id, name=item.name, unit=item.unit)
            )
            if in_window and operation.kind == "count":
                row.count_delta += movement.quantity
            if movement.quantity >= 0:
                continue
            quantity = -movement.quantity
            value, unknown = pools[lot.id].take(quantity)
            input_value += value
            unknown_input |= unknown > 0
            if linked_sale:
                previous = line_values.get(key, ZERO)
                line_values[key] = (
                    previous + value if previous is not None and unknown == 0 else None
                )
            if not in_window:
                continue
            if operation.kind == "consume":
                row.consumed_quantity += quantity
                consumed_values[item.id] += value
                row.unvalued_consumption_quantity += unknown
            elif operation.kind == "waste":
                row.waste_quantity += quantity
                waste_values[item.id] += value
                row.unvalued_waste_quantity += unknown
            elif operation.kind == "production":
                row.production_input_quantity += quantity
        positives = [entry for entry in entries if entry[0].quantity > 0]
        total_positive = sum((entry[0].quantity for entry in positives), ZERO)
        for movement, _, lot, _ in positives:
            incoming_value: Decimal | None = None
            if operation.kind == "receipt" and operation.id in receipt_values:
                incoming_value = receipt_values[operation.id] * movement.quantity / total_positive
            elif operation.kind == "production" and any(entry[0].quantity < 0 for entry in entries):
                incoming_value = input_value * movement.quantity / total_positive
            # Partial ingredient evidence remains a known lower bound even when
            # the complete cost of every produced unit is still unknown.
            pools[lot.id].add(
                movement.quantity,
                incoming_value,
                fully_valued=not (operation.kind == "production" and unknown_input),
            )
    for item_id, row in usage.items():
        row.known_consumption_cost_cents = cents(consumed_values[item_id])
        row.known_waste_cost_cents = cents(waste_values[item_id])
    return StockCosts(
        [
            row
            for row in usage.values()
            if row.consumed_quantity
            or row.waste_quantity
            or row.count_delta
            or row.production_input_quantity
        ],
        {key: cents(value) if value is not None else None for key, value in line_values.items()},
    )
