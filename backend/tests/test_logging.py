"""Authentication query credentials must not reach HTTP or WebSocket logs."""

from __future__ import annotations

import logging

from uvicorn.logging import AccessFormatter

from app.logging_config import _SensitiveFilter


def test_query_redaction_preserves_access_formatter_arguments() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("synthetic-client", "GET", "/ws?token=synthetic-secret&room=demo", "1.1", 200),
        None,
    )
    assert _SensitiveFilter().filter(record)
    formatted = AccessFormatter("%(request_line)s %(status_code)s", use_colors=False).format(record)
    assert "synthetic-secret" not in formatted
    assert "/ws?token=***&room=demo" in formatted and "200 OK" in formatted


def test_uvicorn_websocket_logger_masks_tokens_before_handlers() -> None:
    captured: list[str] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(record.getMessage())

    logger = logging.getLogger("uvicorn.error")
    handler = Capture()
    logger.addHandler(handler)
    try:
        logger.warning("WebSocket %s [accepted]", "/ws?token=synthetic-websocket-secret")
        logger.warning("/callback?access_token=synthetic-access&refresh_token=synthetic-refresh")
        logger.warning(
            "Login %(password)s at %(url)s",
            {"password": "synthetic-password", "url": "/ws?TOKEN=synthetic-uppercase"},
        )
    finally:
        logger.removeHandler(handler)
    assert len(captured) == 3
    assert all("synthetic-" not in entry for entry in captured)
    assert captured[0] == "WebSocket /ws?token=*** [accepted]"
