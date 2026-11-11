"""Reverse food tracing from a sold dish to production and supplier receipts."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select

from app.gastro import service as svc
from app.gastro.inventory_models import StockLot, StockMovement, StockOperation
from app.gastro.inventory_schemas import LotRead
from app.gastro.purchasing_models import PurchaseOrder, PurchaseOrderLine, PurchaseReceipt
from app.gastro.router import DB, Actor, private_response

router = APIRouter(dependencies=[Depends(private_response)])


class SourceReceipt(BaseModel):
    receipt_id: uuid.UUID
    purchase_order_id: uuid.UUID
    supplier_id: uuid.UUID
    operation_id: uuid.UUID


class OrderProvenance(BaseModel):
    order_id: uuid.UUID
    lots: list[LotRead]
    operation_ids: list[uuid.UUID]
    receipts: list[SourceReceipt]
    truncated: bool
    coverage: str


@router.get(
    "/venues/{venue_id}/orders/{order_id}/provenance",
    response_model=OrderProvenance,
    status_code=200,
    summary="Bon rückwärts bis zu Zutatenchargen und Wareneingängen verfolgen",
)
async def provenance(
    venue_id: uuid.UUID, order_id: uuid.UUID, user: Actor, db: DB
) -> OrderProvenance:
    await svc.venue_access(db, user, venue_id, svc.KITCHEN)
    order = await svc.order_for_venue(db, venue_id, order_id)
    initial = set(
        (
            await db.execute(
                select(StockOperation.id).where(
                    StockOperation.venue_id == venue_id,
                    StockOperation.details["order_id"].astext == str(order_id),
                    StockOperation.kind == "consume",
                )
            )
        ).scalars()
    )
    seen: set[uuid.UUID] = set()
    operations = set(initial)
    frontier = initial
    truncated = False
    while frontier:
        inputs = (
            set(
                (
                    await db.execute(
                        select(StockMovement.lot_id).where(
                            StockMovement.venue_id == venue_id,
                            StockMovement.operation_id.in_(frontier),
                            StockMovement.quantity < 0,
                        )
                    )
                ).scalars()
            )
            - seen
        )
        seen.update(inputs)
        if len(seen) > 500:
            truncated = True
            break
        parents = (
            set(
                (
                    await db.execute(
                        select(StockOperation.id)
                        .join(StockMovement, StockMovement.operation_id == StockOperation.id)
                        .where(
                            StockOperation.venue_id == venue_id,
                            StockMovement.venue_id == venue_id,
                            StockMovement.lot_id.in_(inputs),
                            StockMovement.quantity > 0,
                            StockOperation.kind.in_(["production", "receipt"]),
                        )
                    )
                ).scalars()
            )
            if inputs
            else set()
        )
        frontier = parents - operations
        operations.update(frontier)
    lots = list(
        (
            await db.execute(
                select(StockLot)
                .where(StockLot.venue_id == venue_id, StockLot.id.in_(seen))
                .order_by(StockLot.code, StockLot.id)
            )
        ).scalars()
    )
    receipts = (
        await db.execute(
            select(PurchaseReceipt, PurchaseOrder.id, PurchaseOrder.supplier_id)
            .join(PurchaseOrderLine, PurchaseOrderLine.id == PurchaseReceipt.line_id)
            .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.order_id)
            .where(
                PurchaseReceipt.venue_id == venue_id,
                PurchaseOrder.venue_id == venue_id,
                PurchaseReceipt.stock_operation_id.in_(operations),
            )
        )
    ).all()
    recipe_lines = sum(
        bool(line.get("recipe_id"))
        for line in order.lines
        if line.get("kind", "product") == "product"
    )
    return OrderProvenance(
        order_id=order_id,
        lots=[LotRead.model_validate(lot) for lot in lots],
        operation_ids=sorted(operations),
        receipts=[
            SourceReceipt(
                receipt_id=row.id,
                purchase_order_id=purchase_order_id,
                supplier_id=supplier,
                operation_id=row.stock_operation_id,
            )
            for row, purchase_order_id, supplier in receipts
            if row.stock_operation_id is not None
        ],
        truncated=truncated,
        coverage=(
            "Erfasste Rezeptverbräuche; nicht rezeptgebundene Altpositionen benötigen manuelle Zuordnung."
            if recipe_lines
            else "Keine rezeptgebundenen Verbrauchsbuchungen. Historische Herkunft wird nicht erfunden."
        ),
    )
