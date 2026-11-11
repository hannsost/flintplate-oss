"""DMS expiry notification job (Sprint 3.1).

Runs daily at 07:00.  Sends in-app notifications for documents that expire
within the next `expires_reminder_days` days.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select, text

from app.database import AsyncSessionLocal

log = logging.getLogger(__name__)


async def send_doc_expiry_notifications() -> None:
    log.info("DMS expiry check starting")
    async with AsyncSessionLocal() as db:
        try:
            await _run(db)
        except Exception:
            log.exception("DMS expiry notification job failed")


async def _run(db) -> None:  # type: ignore[no-untyped-def]
    from app.dms.models import Document
    from app.notifications.models import Notification

    now = datetime.now(UTC)

    result = await db.execute(
        select(Document).where(
            Document.status == "active",
            Document.expires_at.isnot(None),
            Document.expires_at > now,
        )
    )
    docs = result.scalars().all()

    sent = 0
    for doc in docs:
        if not doc.expires_at:
            continue
        days_left = (doc.expires_at - now).days
        if days_left > doc.expires_reminder_days:
            continue

        # Create in-app notification for the document creator
        if not doc.created_by:
            continue

        # Check if we already sent this reminder recently (avoid duplicates)
        existing = await db.execute(
            text("""
                SELECT id FROM notifications
                WHERE user_id = :uid
                  AND type = 'doc_expiry'
                  AND metadata->>'document_id' = :did
                  AND created_at > NOW() - INTERVAL '1 day'
                """),
            {"uid": str(doc.created_by), "did": str(doc.id)},
        )
        if existing.fetchone():
            continue

        notif = Notification(
            user_id=doc.created_by,
            type="doc_expiry",
            title="Dokument läuft bald ab",
            body=f'Das Dokument „{doc.name}" läuft in {days_left} Tag(en) ab.',
            meta={"document_id": str(doc.id), "days_left": days_left},
        )
        db.add(notif)
        sent += 1

    await db.commit()
    log.info("DMS expiry check done — %d notifications sent", sent)
