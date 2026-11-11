"""Additive cash tips: actual receipts, compensating returns, whole sources."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.gastro import cash
from app.gastro import service as svc
from app.gastro.models import Venue
from app.gastro.payer_tip_models import PayerTipEntry, TipRunSource
from app.gastro.payer_tip_schemas import PayerTipRead, PayerTipReturnInput


async def returned_cents(db: AsyncSession, source_id: uuid.UUID) -> int:
    return -int(
        (
            await db.execute(
                select(func.coalesce(func.sum(PayerTipEntry.amount_cents), 0)).where(
                    PayerTipEntry.original_id == source_id
                )
            )
        ).scalar_one()
    )


async def read_tip(db: AsyncSession, entry: PayerTipEntry) -> PayerTipRead:
    result = PayerTipRead.model_validate(entry)
    if entry.kind == "received":
        result.refunded_cents = await returned_cents(db, entry.id)
        result.tip_run_id = (
            await db.execute(
                select(TipRunSource.run_id).where(TipRunSource.payer_tip_id == entry.id)
            )
        ).scalar_one_or_none()
        result.refundable_cents = (
            0 if result.tip_run_id else entry.amount_cents - result.refunded_cents
        )
    return result


async def available_tips(
    db: AsyncSession, venue_id: uuid.UUID, start: datetime, end: datetime
) -> list[tuple[PayerTipEntry, int]]:
    entries = list(
        (
            await db.execute(
                select(PayerTipEntry)
                .where(
                    PayerTipEntry.venue_id == venue_id,
                    PayerTipEntry.kind == "received",
                    PayerTipEntry.created_at >= start,
                    PayerTipEntry.created_at < end,
                    ~select(TipRunSource.id)
                    .where(TipRunSource.payer_tip_id == PayerTipEntry.id)
                    .exists(),
                )
                .order_by(PayerTipEntry.id)
            )
        ).scalars()
    )
    result: list[tuple[PayerTipEntry, int]] = []
    for entry in entries:
        remaining = entry.amount_cents - await returned_cents(db, entry.id)
        if remaining:
            result.append((entry, remaining))
    return result


async def return_tip(
    db: AsyncSession,
    venue: Venue,
    actor_id: uuid.UUID,
    source_id: uuid.UUID,
    data: PayerTipReturnInput,
) -> PayerTipRead:
    fingerprint = cash.command_hash("payer-tip-return", source_id, data)
    prior = (
        await db.execute(
            select(PayerTipEntry).where(
                PayerTipEntry.venue_id == venue.id, PayerTipEntry.request_key == data.request_key
            )
        )
    ).scalar_one_or_none()
    if prior:
        if prior.request_hash != fingerprint:
            raise HTTPException(409, "Vorgangs-ID gehört zu einer anderen Trinkgeldrückgabe.")
        return await read_tip(db, prior)
    source = (
        await db.execute(
            select(PayerTipEntry).where(
                PayerTipEntry.venue_id == venue.id,
                PayerTipEntry.id == source_id,
                PayerTipEntry.kind == "received",
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(404, "Original-Trinkgeldbeleg nicht gefunden.")
    await cash.session_for(db, venue.id, data.session_id, actor_id, "manager")
    await cash.ledger_lock(db, venue.id)
    read = await read_tip(db, source)
    if read.tip_run_id:
        raise HTTPException(409, "Dieses Trinkgeld ist bereits verbindlich verteilt.")
    if data.amount_cents > read.refundable_cents:
        raise HTTPException(409, "Trinkgeld wurde bereits zurückgegeben oder Betrag ist zu hoch.")
    if data.amount_cents > await cash.drawer_balance(db, data.session_id):
        raise HTTPException(409, "Die Schichtkasse enthält nicht genug Bargeld.")
    entry = PayerTipEntry(
        venue_id=venue.id,
        payment_group_id=source.payment_group_id,
        session_id=data.session_id,
        original_id=source.id,
        kind="returned",
        amount_cents=-data.amount_cents,
        currency=source.currency,
        actor_id=actor_id,
        payer_tab_id=source.payer_tab_id,
        payer_label=source.payer_label,
        recipient_id=source.recipient_id,
        request_key=data.request_key,
        request_hash=fingerprint,
        reason=data.reason,
    )
    db.add(entry)
    await db.flush()
    svc.event(
        db,
        venue.id,
        "tips.actual_return",
        entry.id,
        {
            "original_id": str(source.id),
            "amount_cents": data.amount_cents,
            "session_id": str(data.session_id),
            "reason": data.reason,
        },
        actor_id,
    )
    return await read_tip(db, entry)
