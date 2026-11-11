"""Structured logging configuration for palmscout.

Sprint 0.8 will add Sentry DSN. For now: JSON to stdout in production,
human-readable in development.
"""

from __future__ import annotations

import logging
import re
import sys

from app.config import get_settings

settings = get_settings()


class _SensitiveFilter(logging.Filter):
    """Strip fields that must never appear in logs (DSGVO)."""

    _BLOCKED = frozenset({"password", "hashed_password", "token", "secret_key"})
    _QUERY_SECRETS = re.compile(
        r"([?&](?:token|access_token|refresh_token|api_key|password|secret_key)=)[^&\s\"']*",
        re.IGNORECASE,
    )

    @classmethod
    def redact(cls, value: object) -> object:
        return cls._QUERY_SECRETS.sub(r"\1***", value) if isinstance(value, str) else value

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self.redact(record.msg)
        if isinstance(record.args, dict):
            record.args = {
                k: "***" if k in self._BLOCKED else self.redact(v) for k, v in record.args.items()
            }
        elif isinstance(record.args, tuple):
            record.args = tuple(self.redact(v) for v in record.args)
        return True


def configure_logging() -> None:
    level = logging.DEBUG if not settings.is_production else logging.INFO

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_SensitiveFilter())

    if settings.is_production:
        # JSON formatter – Sprint 0.8 will replace with structlog
        fmt = (
            '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}'
        )
    else:
        fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

    handler.setFormatter(logging.Formatter(fmt))

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Uvicorn owns handlers outside the root logger, including WebSocket URL logging.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).addFilter(_SensitiveFilter())

    # Silence noisy third-party loggers
    for noisy in ("sqlalchemy.engine", "asyncio", "multipart"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
