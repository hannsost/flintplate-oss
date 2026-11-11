from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.gastro import service as svc
from app.gastro.models import GuestAccount, LoyaltyEntry, Order, Voucher, VoucherEntry
from app.gastro.router import DB, Actor, private_response
from app.gastro.schemas import (
    DiscountInput,
    LineRead,
    OrderRead,
    VersionInput,
    VoucherCreated,
    VoucherInput,
    VoucherRead,
    VoucherRedeem,
)

router = APIRouter(dependencies=[Depends(private_response)])


def editable(order: Order) -> None:
    if order.cancellation_units:
        raise HTTPException(
            409,
            "Der Originalbon enthält Stornobelege. Rabatt und Gutscheinzuordnung sind gesperrt.",
        )
    if order.status not in svc.ACTIVE_ORDER_STATES or order.pos_requested or order.paid_at:
        raise HTTPException(409, "Die Bestellung ist abgeschlossen oder bereits an der Kasse.")


@router.post(
    "/venues/{venue_id}/orders/{order_id}/discount",
    response_model=OrderRead,
    status_code=200,
    summary="Begründeten Rabatt mit Steuerausweis vor Kassenübergabe anwenden",
)
async def discount(
    venue_id: uuid.UUID, order_id: uuid.UUID, data: DiscountInput, user: Actor, db: DB
) -> Order:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    order = await svc.order_for_venue(db, venue_id, order_id, lock=True)
    svc.check_version(order.version, data.version)
    editable(order)
    if order.voucher_cents:
        raise HTTPException(409, "Gutscheinzahlung zuerst aufheben.")
    lines = [LineRead.model_validate(line) for line in order.lines]
    for line in lines:
        gross = line.price_cents * line.quantity
        # Deposits retain their face value. A new discount replaces the previous one.
        line.discount_cents = (
            0
            if line.kind == "deposit"
            else int(
                (Decimal(gross) * data.percent / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            )
        )
        line.total_cents = gross - line.discount_cents
        line.tax_cents = int(
            (Decimal(line.total_cents) * line.tax_rate_bps / (10000 + line.tax_rate_bps)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
        )
    order.lines = [line.model_dump(mode="json") for line in lines]
    order.discount_cents = sum(line.discount_cents for line in lines)
    order.discount_reason = data.reason.strip()
    order.total_cents = sum(line.total_cents for line in lines)
    order.version += 1
    svc.event(
        db,
        venue_id,
        "order.discounted",
        order.id,
        {
            "percent": data.percent,
            "reason": order.discount_reason,
            "discount_cents": order.discount_cents,
            "version": order.version,
        },
        user.id,
    )
    await db.flush()
    return order


@router.get(
    "/venues/{venue_id}/vouchers",
    response_model=list[VoucherRead],
    status_code=200,
    summary="Gutscheinsalden ohne Einlösecodes",
)
async def vouchers(venue_id: uuid.UUID, user: Actor, db: DB) -> list[Voucher]:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS)
    return list(
        (
            await db.execute(
                select(Voucher)
                .where(Voucher.venue_id == venue_id)
                .order_by(Voucher.created_at.desc())
                .limit(200)
            )
        ).scalars()
    )


@router.post(
    "/venues/{venue_id}/vouchers",
    response_model=VoucherCreated,
    status_code=201,
    summary="Extern bezahlten oder als Kulanz freigegebenen Gutschein ausgeben",
)
async def issue(venue_id: uuid.UUID, data: VoucherInput, user: Actor, db: DB) -> VoucherCreated:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    prior = (
        await db.execute(
            select(VoucherEntry).where(
                VoucherEntry.venue_id == venue_id, VoucherEntry.request_key == data.request_key
            )
        )
    ).scalar_one_or_none()
    if prior:
        if prior.kind != "issue" or prior.request_hash != svc.digest(data):
            raise HTTPException(409, "Vorgangs-ID bereits anders verwendet.")
        voucher = (
            await db.execute(select(Voucher).where(Voucher.id == prior.voucher_id))
        ).scalar_one()
        return VoucherCreated(voucher=VoucherRead.model_validate(voucher), code=None)
    if data.expires_at <= datetime.now(UTC):
        raise HTTPException(422, "Ablaufdatum muss in der Zukunft liegen.")
    code = "FP-" + secrets.token_hex(12).upper()
    voucher = Voucher(
        venue_id=venue_id,
        code_digest=hashlib.sha256(code.encode()).hexdigest(),
        label=data.label,
        initial_cents=data.amount_cents,
        balance_cents=data.amount_cents,
        expires_at=data.expires_at,
        reference=data.reference,
        request_key=data.request_key,
    )
    db.add(voucher)
    await db.flush()
    db.add(
        VoucherEntry(
            venue_id=venue_id,
            voucher_id=voucher.id,
            amount_cents=data.amount_cents,
            request_key=data.request_key,
            request_hash=svc.digest(data),
            kind="issue",
            actor_id=user.id,
        )
    )
    svc.event(
        db,
        venue_id,
        "voucher.issued",
        voucher.id,
        {"amount_cents": data.amount_cents, "reference": data.reference},
        user.id,
    )
    return VoucherCreated(voucher=VoucherRead.model_validate(voucher), code=code)


@router.post(
    "/venues/{venue_id}/orders/{order_id}/voucher",
    response_model=OrderRead,
    status_code=200,
    summary="Gutschein als Teilzahlung reservieren, ohne den steuerlichen Umsatz zu verändern",
)
async def redeem(
    venue_id: uuid.UUID, order_id: uuid.UUID, data: VoucherRedeem, user: Actor, db: DB
) -> Order:
    await svc.venue_access(db, user, venue_id, svc.SERVICE, lock=True)
    order = await svc.order_for_venue(db, venue_id, order_id, lock=True)
    prior = (
        await db.execute(
            select(VoucherEntry).where(
                VoucherEntry.venue_id == venue_id, VoucherEntry.request_key == data.request_key
            )
        )
    ).scalar_one_or_none()
    if prior:
        if (
            prior.kind != "redeem"
            or prior.order_id != order.id
            or prior.request_hash != svc.digest(data)
        ):
            raise HTTPException(409, "Vorgangs-ID bereits anders verwendet.")
        return order
    svc.check_version(order.version, data.version)
    editable(order)
    code_hash = hashlib.sha256(data.code.strip().upper().encode()).hexdigest()
    voucher = (
        await db.execute(
            select(Voucher)
            .where(Voucher.venue_id == venue_id, Voucher.code_digest == code_hash)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if voucher is None or voucher.expires_at <= datetime.now(UTC):
        raise HTTPException(422, "Gutschein unbekannt oder abgelaufen.")
    if data.amount_cents > min(voucher.balance_cents, order.total_cents - order.voucher_cents):
        raise HTTPException(422, "Betrag übersteigt Gutscheinrest oder offenen Bestellbetrag.")
    voucher.balance_cents -= data.amount_cents
    order.voucher_cents += data.amount_cents
    order.version += 1
    db.add(
        VoucherEntry(
            venue_id=venue_id,
            voucher_id=voucher.id,
            order_id=order.id,
            amount_cents=-data.amount_cents,
            request_key=data.request_key,
            request_hash=svc.digest(data),
            kind="redeem",
            actor_id=user.id,
        )
    )
    svc.event(
        db,
        venue_id,
        "order.voucher_applied",
        order.id,
        {"voucher_id": str(voucher.id), "amount_cents": data.amount_cents},
        user.id,
    )
    await db.flush()
    return order


@router.post(
    "/venues/{venue_id}/orders/{order_id}/voucher-release",
    response_model=OrderRead,
    status_code=200,
    summary="Gutschein-Teilzahlungen vor Kassenübergabe zurückbuchen",
)
async def release(
    venue_id: uuid.UUID, order_id: uuid.UUID, data: VersionInput, user: Actor, db: DB
) -> Order:
    await svc.venue_access(db, user, venue_id, svc.MANAGERS, lock=True)
    order = await svc.order_for_venue(db, venue_id, order_id, lock=True)
    svc.check_version(order.version, data.version)
    editable(order)
    await release_order_vouchers(db, order, user.id)
    order.version += 1
    await db.flush()
    return order


async def release_order_vouchers(db: DB, order: Order, user_id: uuid.UUID) -> None:
    """Release outstanding voucher reservations within the caller's locked transaction."""
    if not order.voucher_cents:
        return
    entries = (
        (
            await db.execute(
                select(VoucherEntry)
                .where(VoucherEntry.order_id == order.id)
                .order_by(VoucherEntry.voucher_id)
            )
        )
        .scalars()
        .all()
    )
    balances: dict[uuid.UUID, int] = {}
    for entry in entries:
        balances[entry.voucher_id] = balances.get(entry.voucher_id, 0) - entry.amount_cents
    for voucher_id, amount in balances.items():
        if amount <= 0:
            continue
        voucher = (
            await db.execute(select(Voucher).where(Voucher.id == voucher_id).with_for_update())
        ).scalar_one()
        voucher.balance_cents += amount
        db.add(
            VoucherEntry(
                venue_id=order.venue_id,
                voucher_id=voucher_id,
                order_id=order.id,
                amount_cents=amount,
                request_key=uuid.uuid4(),
                request_hash=svc.digest(VersionInput(version=order.version)),
                kind="release",
                actor_id=user_id,
            )
        )
    order.voucher_cents = 0
    svc.event(db, order.venue_id, "order.voucher_released", order.id, {}, user_id)
    await db.flush()


async def earn_points(db: DB, order: Order) -> None:
    if order.customer_id is None:
        return
    account = (
        await db.execute(
            select(GuestAccount).where(GuestAccount.id == order.customer_id).with_for_update()
        )
    ).scalar_one()
    if (await db.execute(select(LoyaltyEntry.id).where(LoyaltyEntry.order_id == order.id))).first():
        return
    # One point per paid euro of products/activities, excluding packaging and deposits.
    eligible = sum(
        LineRead.model_validate(line).total_cents
        for line in order.lines
        if line.get("kind", "product") in {"product", "activity"}
    )
    eligible -= sum(
        row.unpaid_credit_cents
        for row in order.cancellation_units
        if row.kind in {"product", "activity"}
    )
    points = eligible // 100
    account.points += points
    db.add(
        LoyaltyEntry(
            account_id=account.id,
            order_id=order.id,
            points=points,
            reason="Bestellung durch Kassenadapter bestätigt",
        )
    )
