"""Custom ASGI middleware for palmscout.

- RequestIDMiddleware:      injects X-Request-ID into every request/response
- TimingMiddleware:         adds X-Process-Time header for performance tracking
- TenantFromHostMiddleware: resolves tenant_id from custom Host header (Sprint 2.6)
"""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attaches a unique request ID to every request and response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


class TimingMiddleware(BaseHTTPMiddleware):
    """Records wall-clock processing time per request (ms)."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Process-Time"] = f"{elapsed_ms:.2f}ms"
        return response


class TenantFromHostMiddleware(BaseHTTPMiddleware):
    """Resolves tenant_id from a custom Host header (Sprint 2.6 – white-label domains).

    When a request arrives on a custom domain (e.g. ``recruit.acme.de``) that is
    registered in ``customers.custom_domain``, this middleware sets
    ``request.state.host_tenant_id`` so downstream handlers can personalise
    the response.  Requests on the main platform domain leave
    ``request.state.host_tenant_id`` as ``None``.

    A Redis cache (60 s TTL) is used to avoid a DB lookup on every request.
    """

    _CACHE_TTL = 60  # seconds

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request.state.host_tenant_id = None

        host = request.headers.get("host", "").split(":")[0].lower().strip()
        if host and not host.startswith(("localhost", "127.", "0.0.0.0")):
            try:
                tenant_id = await self._resolve(host)
                request.state.host_tenant_id = tenant_id
            except Exception:
                pass  # never block a request due to tenant resolution failure

        return await call_next(request)

    async def _resolve(self, domain: str) -> str | None:
        from sqlalchemy import select

        from app.admin.models import Customer
        from app.cache import redis_client
        from app.database import AsyncSessionLocal

        cache_key = f"custom_domain:{domain}"

        async with redis_client() as cache:
            cached = await cache.get(cache_key)
            if cached is not None:
                value = cached.decode() if isinstance(cached, bytes) else cached
                return str(value) if value != "__none__" else None

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(Customer.id).where(Customer.custom_domain == domain)
                )
                row = result.scalar_one_or_none()
                tenant_id = str(row) if row else None
            await cache.set(cache_key, tenant_id or "__none__", ex=self._CACHE_TTL)
            return tenant_id
