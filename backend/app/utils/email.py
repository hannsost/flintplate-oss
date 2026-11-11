"""Email validation and normalization utilities."""

from __future__ import annotations

import re

_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def normalize_email(email: str) -> str:
    """Lowercase and strip whitespace from an email address."""
    return email.strip().lower()


def is_valid_email(email: str) -> bool:
    """Basic RFC-5322-ish email format check."""
    return bool(_EMAIL_RE.match(email))
