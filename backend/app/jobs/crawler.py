"""Job crawler – Sprint 0.4.
RSS feeds: StepStone, Indeed (public RSS endpoints).
Phase 0: mock data generator for local dev without API keys.
"""

from __future__ import annotations

import logging
import random
import uuid
from datetime import UTC, datetime, timedelta

import feedparser

from app.jobs.schemas import JobPostingCreate

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known public RSS endpoints for job boards
# ---------------------------------------------------------------------------

FEED_URLS: dict[str, str] = {
    "stepstone_de": "https://www.stepstone.de/rss/jobsuche/?what=developer&where=deutschland",
    "indeed_de": "https://de.indeed.com/rss?q=developer&l=Deutschland",
    "remotive": "https://remotive.com/remote-jobs/feed/software-dev",
    "weworkremotely_programming": "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "stackoverflow_jobs": "https://stackoverflow.com/jobs/feed?r=true&tl=python",
}

# ---------------------------------------------------------------------------
# RSS feed crawler
# ---------------------------------------------------------------------------

_MAX_ENTRIES_PER_FEED = 50


async def fetch_rss_jobs(feed_url: str, source: str) -> list[JobPostingCreate]:
    """Fetch and parse a single RSS feed, returning a list of JobPostingCreate.

    Errors are caught and logged; an empty list is returned on any failure so
    that a broken feed never crashes the caller.
    """
    try:
        # feedparser is synchronous – acceptable for a background crawler task;
        # wrap in a thread executor if strict async-purity is required later.
        parsed = feedparser.parse(feed_url)

        if parsed.get("bozo") and parsed.get("bozo_exception"):
            logger.warning(
                "Bozo feed detected for %s (%s): %s",
                source,
                feed_url,
                parsed["bozo_exception"],
            )

        entries = parsed.get("entries", [])[:_MAX_ENTRIES_PER_FEED]
        jobs: list[JobPostingCreate] = []

        for entry in entries:
            title: str = entry.get("title", "").strip()
            if not title:
                continue

            link: str = entry.get("link", "").strip()
            summary: str = entry.get("summary", entry.get("description", "")).strip()
            company: str = (
                entry.get("author", "") or entry.get("source", {}).get("title", "") or "Unknown"
            ).strip()

            # Parse published date if available
            published_at: datetime | None = None
            if "published_parsed" in entry and entry["published_parsed"]:
                import time as _time

                published_at = datetime.fromtimestamp(
                    _time.mktime(entry["published_parsed"]), tz=UTC
                )

            jobs.append(
                JobPostingCreate(
                    title=title,
                    company=company,
                    description=summary or None,
                    url=link or None,
                    source=source,
                    posted_at=published_at,
                )
            )

        logger.info("Fetched %d jobs from %s (%s)", len(jobs), source, feed_url)
        return jobs

    except Exception:
        logger.exception("Failed to fetch RSS feed for source=%s url=%s", source, feed_url)
        return []


# ---------------------------------------------------------------------------
# Mock job generator (Phase 0 – local dev without API keys)
# ---------------------------------------------------------------------------

_ROLES: list[dict[str, list[str] | str | int]] = [
    {
        "title": "Senior Python / FastAPI Engineer",
        "company_pool": ["FinTech GmbH", "DataStack AG", "CloudNine Solutions"],
        "skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "Redis"],
        "salary_min": 80_000,
        "salary_max": 110_000,
    },
    {
        "title": "Backend Engineer (Python)",
        "company_pool": ["Scaleway DE", "NovaSoft", "BlueSky Systems"],
        "skills": ["Python", "Django", "REST APIs", "Celery", "AWS"],
        "salary_min": 70_000,
        "salary_max": 95_000,
    },
    {
        "title": "Full-Stack Engineer – React & FastAPI",
        "company_pool": ["StartupXYZ", "DigitalHub GmbH", "MediaTech SE"],
        "skills": ["React", "TypeScript", "FastAPI", "PostgreSQL", "GraphQL"],
        "salary_min": 75_000,
        "salary_max": 105_000,
    },
    {
        "title": "Frontend Developer (React / TypeScript)",
        "company_pool": ["UX Studio Berlin", "Kreativ GmbH", "WebFront AG"],
        "skills": ["React", "TypeScript", "CSS-in-JS", "Jest", "Webpack"],
        "salary_min": 65_000,
        "salary_max": 90_000,
    },
    {
        "title": "Data Scientist – NLP & ML",
        "company_pool": ["AI Labs GmbH", "PredictAI", "DataMind Solutions"],
        "skills": ["Python", "PyTorch", "scikit-learn", "NLP", "Pandas", "SQL"],
        "salary_min": 85_000,
        "salary_max": 120_000,
    },
    {
        "title": "Machine Learning Engineer",
        "company_pool": ["DeepTech Berlin", "Neural Systems", "MLOps GmbH"],
        "skills": ["Python", "TensorFlow", "MLflow", "Kubernetes", "Spark"],
        "salary_min": 90_000,
        "salary_max": 120_000,
    },
    {
        "title": "DevOps / Platform Engineer",
        "company_pool": ["Infra24 GmbH", "CloudOps SE", "SRE Systems"],
        "skills": ["Kubernetes", "Terraform", "AWS", "CI/CD", "Prometheus", "Docker"],
        "salary_min": 80_000,
        "salary_max": 110_000,
    },
    {
        "title": "Site Reliability Engineer (SRE)",
        "company_pool": ["Reliability Corp", "TechOps AG", "ScaleOps GmbH"],
        "skills": ["Linux", "Kubernetes", "Go", "Prometheus", "Grafana"],
        "salary_min": 85_000,
        "salary_max": 115_000,
    },
    {
        "title": "Junior Python Developer",
        "company_pool": ["CodeBoost GmbH", "DevStart Berlin", "LearnTech AG"],
        "skills": ["Python", "Django", "Git", "SQL", "REST APIs"],
        "salary_min": 45_000,
        "salary_max": 62_000,
    },
    {
        "title": "TypeScript / Node.js Backend Engineer",
        "company_pool": ["NodeWorks GmbH", "APIFirst Solutions", "JSStack SE"],
        "skills": ["TypeScript", "Node.js", "Express", "PostgreSQL", "Docker"],
        "salary_min": 72_000,
        "salary_max": 98_000,
    },
]

_LOCATIONS: list[str] = ["Berlin", "München", "Hamburg", "Remote", "Frankfurt", "Köln", "Remote"]
_SOURCES: list[str] = ["mock", "stepstone_mock", "indeed_mock", "linkedin_mock"]


async def generate_mock_jobs(count: int = 20) -> list[JobPostingCreate]:
    """Generate *count* realistic mock job postings for local development.

    Produces a varied mix of Python/FastAPI, React/TypeScript, Data Science,
    and DevOps roles across German cities and remote positions.
    """
    rng = random.Random()  # unseeded → different results each call
    jobs: list[JobPostingCreate] = []

    for _i in range(count):
        role = rng.choice(_ROLES)
        location = rng.choice(_LOCATIONS)
        is_remote: bool = location == "Remote" or rng.random() < 0.40

        company_pool: list[str] = list(role["company_pool"])  # type: ignore[arg-type]
        company: str = rng.choice(company_pool)

        salary_min: int = int(role["salary_min"])  # type: ignore[arg-type]
        salary_max: int = int(role["salary_max"])  # type: ignore[arg-type]
        # Add small random jitter (±5 %)
        jitter = rng.randint(-3_000, 3_000)
        salary_min = max(35_000, salary_min + jitter)
        salary_max = min(130_000, salary_max + jitter)

        all_skills: list[str] = list(role["skills"])  # type: ignore[arg-type]
        k = rng.randint(3, min(6, len(all_skills)))
        required_skills: list[str] = rng.sample(all_skills, k)

        title: str = str(role["title"])
        description: str = (
            f"We are looking for a {title} to join our team in {location}. "
            f"You will work with {', '.join(required_skills[:3])} on challenging "
            "products used by thousands of users. Competitive compensation, flexible "
            "hours, and a collaborative remote-friendly culture."
        )

        days_ago: int = rng.randint(0, 30)
        published_at = datetime.now(tz=UTC) - timedelta(days=days_ago)

        fake_id = str(uuid.uuid4())[:8]
        url: str = f"https://jobs.mock.palmscout.invalid/posting/{fake_id}"

        jobs.append(
            JobPostingCreate(
                title=title,
                company=company,
                description=description,
                url=url,
                source=rng.choice(_SOURCES),
                location=location if not is_remote else "Remote",
                is_remote=is_remote,
                salary_min=salary_min,
                salary_max=salary_max,
                required_skills=required_skills,
                posted_at=published_at,
            )
        )

    logger.info("Generated %d mock job postings", len(jobs))
    return jobs
