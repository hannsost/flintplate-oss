"""Zentraler LLM-Client mit Dev-Throttle-Support und Tenant-Usage-Tracking.

Alle AI-Generatoren sollen get_llm() statt direktem ChatOpenAI() verwenden.
Einstellbar via .env:
  AI_MOCK_MODE=true        → gibt None zurück, Generator nutzt Fallback
  AI_MAX_TOKENS=500        → Token-Limit pro Request
  AI_REQUESTS_PER_MIN=5   → Einfaches In-Memory Rate-Limit (0 = aus)

Usage-Tracking:
  track_ai_usage(tenant_id, module_key) → inkrementiert customer_modules.usage_current
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

log = logging.getLogger(__name__)

# Einfaches In-Memory Token-Bucket für LLM-Calls
_bucket_lock = asyncio.Lock()
_bucket_tokens: float = 0.0
_bucket_last_refill: float = 0.0


async def _check_rate_limit(per_min: int) -> bool:
    """Returns True if the call is allowed, False if rate-limited."""
    if per_min <= 0:
        return True
    global _bucket_tokens, _bucket_last_refill
    async with _bucket_lock:
        now = time.monotonic()
        elapsed = now - _bucket_last_refill
        _bucket_last_refill = now
        # Refill tokens based on elapsed time
        _bucket_tokens = min(float(per_min), _bucket_tokens + elapsed * (per_min / 60.0))
        if _bucket_tokens >= 1.0:
            _bucket_tokens -= 1.0
            return True
        return False


async def get_llm(
    temperature: float = 0.7, *, max_retries: int = 2, max_tokens: int | None = None
) -> Any | None:
    """Return a configured ChatOpenAI instance, or None if mock mode / rate-limited.

    Usage in generators:
        llm = await get_llm()
        if llm is None:
            return mock_result()
        response = await llm.ainvoke(messages)
    """
    from app.config import get_settings

    s = get_settings()

    if s.ai_mock_mode:
        log.debug("AI_MOCK_MODE=true – LLM-Call übersprungen")
        return None

    if not await _check_rate_limit(s.ai_requests_per_min):
        log.warning(
            "AI rate limit erreicht (%d/min) – LLM-Call übersprungen", s.ai_requests_per_min
        )
        return None

    if not s.openai_api_key and not s.openai_base_url:
        return None

    try:
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": s.openai_model,
            "api_key": s.openai_api_key or "ollama",
            "temperature": temperature,
            "max_tokens": max_tokens if max_tokens is not None else s.ai_max_tokens,
            "max_retries": max_retries,
        }
        if s.openai_base_url:
            kwargs["base_url"] = s.openai_base_url
        return ChatOpenAI(**kwargs)
    except Exception as exc:
        log.warning("ChatOpenAI init fehlgeschlagen: %s", type(exc).__name__)
        return None


async def track_ai_usage(tenant_id: str | None, module_key: str) -> None:
    """Increment usage_current for a tenant's module. Fire-and-forget, never raises."""
    if not tenant_id:
        return
    try:
        import uuid as _uuid

        from sqlalchemy import update

        from app.admin.models import CustomerModule
        from app.database import AsyncSessionLocal

        tid = _uuid.UUID(tenant_id)
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(CustomerModule)
                .where(
                    CustomerModule.customer_id == tid,
                    CustomerModule.module_key == module_key,
                )
                .values(usage_current=CustomerModule.usage_current + 1)
            )
            await db.commit()
    except Exception as exc:
        log.debug("track_ai_usage failed (non-critical): %s", exc)


async def check_module_enabled(tenant_id: str | None, module_key: str) -> bool:
    """Returns True if module is enabled for the tenant (or no tenant = always True)."""
    if not tenant_id:
        return True
    try:
        import uuid as _uuid

        from app.admin.entitlements import enabled_modules
        from app.database import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            return module_key in await enabled_modules(db, _uuid.UUID(tenant_id))
    except Exception as exc:
        log.debug("check_module_enabled failed (non-critical): %s", exc)
        return False  # Access must stay denied when entitlement lookup fails.
