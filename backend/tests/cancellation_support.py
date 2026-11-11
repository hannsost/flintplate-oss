"""Real reviewed manager approval for financial cancellation tests."""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from tests.hr_support import body
from tests.test_flintplate import Site


async def approve_cancellation(
    client: AsyncClient,
    site: Site,
    order: dict,
    *,
    lines: list[dict] | None = None,
    whole: bool = False,
    include_tip: bool = False,
) -> dict:
    current = body(await client.get(site.path(f"/orders/{order['id']}"), headers=site.headers))
    selection = {
        "version": current["version"],
        "whole_order": whole,
        "include_tip": include_tip,
        "lines": lines or [],
        "reason_code": "guest_request",
        "note": "Synthetic reviewed cancellation",
    }
    preview = body(
        await client.post(
            site.path(f"/orders/{order['id']}/cancellations/preview"),
            headers=site.headers,
            json=selection,
        )
    )
    result = body(
        await client.post(
            site.path(f"/orders/{order['id']}/cancellations"),
            headers=site.headers,
            json={
                **selection,
                "request_key": str(uuid.uuid4()),
                "preview_hash": preview["preview_hash"],
                "approve": True,
            },
        ),
        201,
    )
    assert result["execution"] is not None
    return result["execution"]
