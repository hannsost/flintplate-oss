"""BA jobs require explicit BA_CLIENT_ID and BA_CLIENT_SECRET; no bundled credentials."""

from __future__ import annotations

import contextlib
import logging
import os
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)

_TOKEN_URL = "https://rest.arbeitsagentur.de/oauth/gettoken_cc"
_JOBS_URL = "https://rest.arbeitsagentur.de/jobboerse/jobsuche-service/pc/v4/jobs"

# Credentials must be provided by the operator through the environment.

_MAX_PAGES = 5
_PAGE_SIZE = 25


def _get_credentials() -> tuple[str, str]:
    cid = os.getenv("BA_CLIENT_ID") or ""
    secret = os.getenv("BA_CLIENT_SECRET") or ""
    return cid, secret


async def _fetch_token() -> str | None:
    """Fetch an OAuth2 access token from BA."""
    cid, secret = _get_credentials()
    if not cid or not secret:
        return None
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                _TOKEN_URL,
                data={
                    "grant_type": "client_credentials",
                    "client_id": cid,
                    "client_secret": secret,
                },
            )
            resp.raise_for_status()
            token = resp.json().get("access_token")
            return token if isinstance(token, str) else None
    except Exception as exc:
        log.warning("BA token fetch failed: %s", exc)
        return None


async def fetch_bundesagentur_jobs(
    *,
    keywords: str = "developer",
    location: str = "Deutschland",
    max_jobs: int = 100,
) -> list[dict[str, Any]]:
    """Fetch job listings from Bundesagentur für Arbeit API.

    Returns raw dicts with normalized fields ready for JobPostingCreate.
    """
    token = await _fetch_token()
    if not token:
        log.warning("BA: no token — skipping")
        return []

    try:
        import httpx
    except ImportError:
        log.warning("httpx not installed — cannot fetch BA jobs")
        return []

    jobs: list[dict[str, Any]] = []
    page = 0

    async with httpx.AsyncClient(timeout=15) as client:
        while len(jobs) < max_jobs and page < _MAX_PAGES:
            try:
                resp = await client.get(
                    _JOBS_URL,
                    params={
                        "was": keywords,
                        "wo": location,
                        "page": page,
                        "size": _PAGE_SIZE,
                        "angebotsart": 1,  # 1=Arbeit (employment)
                    },
                    headers={"Authorization": f"Bearer {token}"},
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                log.warning("BA API error on page %d: %s", page, exc)
                break

            stellenangebote = data.get("stellenangebote") or []
            if not stellenangebote:
                break

            for job in stellenangebote:
                arbeitsort = job.get("arbeitsort") or {}
                city = arbeitsort.get("ort") or arbeitsort.get("region") or location
                is_remote = "remote" in (city or "").lower() or "homeoffice" in str(job).lower()

                # Published date
                pub_raw: str | None = job.get("aktuelleVeroeffentlichungsdatum") or job.get(
                    "eintrittsdatum"
                )
                published_at: datetime | None = None
                if pub_raw:
                    with contextlib.suppress(ValueError):
                        published_at = datetime.fromisoformat(pub_raw.replace("Z", "+00:00"))

                ext_id = f"ba_{job.get('hashId', '')}"

                jobs.append(
                    {
                        "title": job.get("titel", "").strip(),
                        "company": job.get("arbeitgeber", "Unknown").strip(),
                        "location": city,
                        "description": job.get("stellenbeschreibung") or None,
                        "url": job.get("externeUrl")
                        or f"https://www.arbeitsagentur.de/jobsuche/jobdetail/{job.get('hashId', '')}",
                        "source": "bundesagentur",
                        "external_id": ext_id,
                        "is_remote": is_remote,
                        "published_at": published_at,
                        "required_skills": [],
                    }
                )

            if len(stellenangebote) < _PAGE_SIZE:
                break  # Last page
            page += 1

    log.info("BA API: fetched %d jobs", len(jobs))
    return jobs[:max_jobs]
