"""AI tracer – async context manager + decorator for logging LLM calls."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

log = logging.getLogger(__name__)


@asynccontextmanager
async def ai_trace(
    trace_type: str,
    user_id: uuid.UUID | None = None,
    model: str | None = None,
    meta: dict[str, Any] | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Async context manager that records timing + token usage for an AI call.

    Usage::

        async with ai_trace("cv_parse", user_id=uid, model="gpt-4o-mini") as t:
            result = await llm_call(...)
            t["prompt_tokens"] = result.usage.prompt_tokens
            t["completion_tokens"] = result.usage.completion_tokens
    """
    ctx: dict[str, Any] = {
        "trace_type": trace_type,
        "user_id": user_id,
        "model": model,
        "meta": meta or {},
        "prompt_tokens": None,
        "completion_tokens": None,
        "total_tokens": None,
        "success": True,
        "error_msg": None,
    }
    start = time.monotonic()
    try:
        yield ctx
    except Exception as exc:
        ctx["success"] = False
        ctx["error_msg"] = str(exc)[:500]
        raise
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        ctx["duration_ms"] = duration_ms
        if ctx.get("prompt_tokens") and ctx.get("completion_tokens"):
            ctx["total_tokens"] = ctx["prompt_tokens"] + ctx["completion_tokens"]

        # Fire-and-forget DB write (non-blocking)
        try:
            from app.database import AsyncSessionLocal
            from app.observability.models import AITrace

            async with AsyncSessionLocal() as db:
                trace = AITrace(
                    user_id=ctx["user_id"],
                    trace_type=ctx["trace_type"],
                    model=ctx["model"],
                    duration_ms=ctx["duration_ms"],
                    prompt_tokens=ctx.get("prompt_tokens"),
                    completion_tokens=ctx.get("completion_tokens"),
                    total_tokens=ctx.get("total_tokens"),
                    success=ctx["success"],
                    error_msg=ctx.get("error_msg"),
                    meta=ctx.get("meta"),
                )
                db.add(trace)
                await db.commit()
        except Exception:
            log.debug("ai_trace: DB write failed", exc_info=True)
