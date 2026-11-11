"""AI Observability endpoints – Sprint 1.8."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.observability.models import AITrace
from app.security import get_current_user
from app.users.models import User

router = APIRouter()


@router.get("/stats", summary="AI-Nutzungsstatistiken (letzten 30 Tage)")
async def get_stats(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Any]:
    since = datetime.now(UTC) - timedelta(days=30)

    scope = [AITrace.created_at >= since]
    if current_user.role == "admin" and current_user.tenant_id is None:
        pass
    elif current_user.role in {"recruiter", "admin"} and current_user.tenant_id is not None:
        scope.append(
            AITrace.user_id.in_(select(User.id).where(User.tenant_id == current_user.tenant_id))
        )
    else:
        scope.append(AITrace.user_id == current_user.id)

    # Total calls
    total = (await db.execute(select(func.count(AITrace.id)).where(*scope))).scalar_one()

    # By type
    by_type_rows = (
        await db.execute(
            select(AITrace.trace_type, func.count(AITrace.id), func.avg(AITrace.duration_ms))
            .where(*scope)
            .group_by(AITrace.trace_type)
            .order_by(func.count(AITrace.id).desc())
        )
    ).all()

    # Token usage
    tokens = (
        await db.execute(
            select(
                func.coalesce(func.sum(AITrace.total_tokens), 0),
                func.coalesce(func.avg(AITrace.duration_ms), 0),
            ).where(*scope)
        )
    ).one()

    # Error rate
    errors = (
        await db.execute(select(func.count(AITrace.id)).where(*scope, AITrace.success.is_(False)))
    ).scalar_one()

    # User's own recent traces
    my_traces = (
        (
            await db.execute(
                select(AITrace)
                .where(AITrace.user_id == current_user.id, AITrace.created_at >= since)
                .order_by(AITrace.created_at.desc())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )

    return {
        "period_days": 30,
        "total_calls": int(total),
        "total_tokens": int(tokens[0]),
        "avg_duration_ms": round(float(tokens[1]), 1),
        "error_rate_pct": round(int(errors) / max(int(total), 1) * 100, 1),
        "by_type": [
            {
                "type": row[0],
                "calls": int(row[1]),
                "avg_ms": round(float(row[2] or 0), 1),
            }
            for row in by_type_rows
        ],
        "my_recent": [
            {
                "id": str(t.id),
                "type": t.trace_type,
                "model": t.model,
                "duration_ms": t.duration_ms,
                "total_tokens": t.total_tokens,
                "success": t.success,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in my_traces
        ],
    }
