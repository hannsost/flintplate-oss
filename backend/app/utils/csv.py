"""Keep user-provided text literal when CSV files are opened in spreadsheets."""

from __future__ import annotations


def literal_cell(value: str | None) -> str:
    text = value or ""
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text
