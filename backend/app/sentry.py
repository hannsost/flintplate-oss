"""Sentry integration – Sprint 0.8.

No-op if SENTRY_DSN is not configured (safe for dev/test).
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def init_sentry(dsn: str | None = None, environment: str = "development") -> None:
    """Initialize Sentry SDK. Silent no-op if dsn is None or empty."""
    if not dsn:
        log.debug("Sentry DSN not configured – Sentry disabled")
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=dsn,
            environment=environment,
            traces_sample_rate=0.2,  # 20% of requests for performance monitoring
            profiles_sample_rate=0.1,
            integrations=[
                FastApiIntegration(transaction_style="url"),
                SqlalchemyIntegration(),
            ],
            send_default_pii=False,  # DSGVO: no PII by default
        )
        log.info("Sentry initialized (env=%s)", environment)
    except ImportError:
        log.warning("sentry-sdk not installed – Sentry disabled")


def capture_exception(exc: Exception) -> None:
    """Capture an exception to Sentry if initialized."""
    try:
        import sentry_sdk

        sentry_sdk.capture_exception(exc)
    except Exception:
        pass
