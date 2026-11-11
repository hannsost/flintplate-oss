"""LangChain + GPT-4o CV parser – Sprint 0.3.

Falls back to regex mock if OPENAI_API_KEY is not configured.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.ai.parsers.schemas import (
    LLMExtractedCV,
    ParsedCV,
    ParsedSkill,
)

log = logging.getLogger(__name__)

# Max chars sent to LLM (≈ 6 000 tokens @ ~4 chars/token)
_MAX_CHARS = 24_000


async def _get_llm() -> Any:
    """Use the shared client so mock mode and request/token limits apply to CVs."""
    from app.ai.client import get_llm

    llm = await get_llm(temperature=0)
    if llm is None:
        raise ValueError("LLM nicht verfügbar (mock mode oder rate limit)")
    return llm


async def parse_with_llm(raw_text: str, pages: list[str]) -> ParsedCV:
    """Extract structured CV data with LangChain structured output.

    Returns a ParsedCV. On any LLM error, falls back to _regex_fallback.
    """
    from app.ai.prompts.cv_extraction import CV_SYSTEM_PROMPT, CV_USER_PROMPT_TEMPLATE

    truncated = raw_text[:_MAX_CHARS]

    try:
        llm = await _get_llm()
        structured_llm = llm.with_structured_output(LLMExtractedCV)

        from langchain_core.messages import HumanMessage, SystemMessage

        messages = [
            SystemMessage(content=CV_SYSTEM_PROMPT),
            HumanMessage(content=CV_USER_PROMPT_TEMPLATE.format(cv_text=truncated)),
        ]

        from app.observability.tracer import ai_trace

        async with ai_trace("cv_parse", model="gpt-4o-mini") as t:
            result: LLMExtractedCV = await structured_llm.ainvoke(messages)
            token_count = len(truncated) // 4
            t["prompt_tokens"] = token_count
            t["completion_tokens"] = token_count // 4

        # Annotate source per item using page heuristic
        _annotate_sources(result, pages)

        # Fill in missing skill categories via keyword table
        for skill in result.skills:
            if not skill.category:
                skill.category = _categorize_skill(skill.name)

        return ParsedCV(
            raw_text=raw_text,
            pages=pages,
            name=result.name,
            email=result.email,
            phone=result.phone,
            location=result.location,
            headline=result.headline,
            summary=result.summary,
            skills=result.skills,
            work_experiences=result.work_experiences,
            educations=result.educations,
            confidence=0.85,
            parser_version="0.3-llm",
            token_count=token_count,
        )

    except Exception as exc:
        log.warning("LLM parser failed (%s), falling back to regex", exc)
        return _regex_fallback(raw_text, pages)


async def parse_with_llm_vision(pages_b64: list[str]) -> ParsedCV:
    """Extract structured CV data from PDF page images via GPT-4o vision.

    Bypasses pypdf text extraction entirely – ideal for two-column / graphical PDFs.
    Falls back to _regex_fallback on any error.
    """
    from app.ai.prompts.cv_extraction import CV_SYSTEM_PROMPT, CV_USER_VISION_PROMPT

    try:
        llm = await _get_llm()
        structured_llm = llm.with_structured_output(LLMExtractedCV)

        from langchain_core.messages import HumanMessage, SystemMessage

        image_parts: list[dict[str, Any]] = [
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/jpeg;base64,{b64}",
                    "detail": "high",
                },
            }
            for b64 in pages_b64
        ]
        messages = [
            SystemMessage(content=CV_SYSTEM_PROMPT),
            HumanMessage(content=[{"type": "text", "text": CV_USER_VISION_PROMPT}, *image_parts]),
        ]

        result: LLMExtractedCV = await structured_llm.ainvoke(messages)

        for skill in result.skills:
            if not skill.category:
                skill.category = _categorize_skill(skill.name)

        token_count = len(pages_b64) * 1500  # rough estimate: ~1 500 tokens/page

        return ParsedCV(
            raw_text="",
            pages=[""] * len(pages_b64),
            name=result.name,
            email=result.email,
            phone=result.phone,
            location=result.location,
            headline=result.headline,
            summary=result.summary,
            skills=result.skills,
            work_experiences=result.work_experiences,
            educations=result.educations,
            confidence=0.92,
            parser_version="0.3-vision",
            token_count=token_count,
        )

    except Exception as exc:
        log.warning("Vision parser failed (%s), falling back to regex", exc)
        return _regex_fallback("", [])


_SKILL_CATEGORIES: dict[str, str] = {
    # Programming Languages
    **{
        k: "Programming Language"
        for k in [
            "python",
            "java",
            "javascript",
            "typescript",
            "c++",
            "c#",
            "c",
            "go",
            "rust",
            "kotlin",
            "swift",
            "r",
            "scala",
            "perl",
            "ruby",
            "php",
            "bash",
            "powershell",
            "matlab",
            "assembler",
            "vba",
            "sql",
            "plsql",
            "transact-sql",
            "html",
            "css",
            "java processing",
            "processing",
        ]
    },
    # Frameworks & Libraries
    **{
        k: "Framework"
        for k in [
            "react",
            "next.js",
            "vue",
            "angular",
            "fastapi",
            "django",
            "flask",
            "spring",
            "express",
            "langchain",
            "tensorflow",
            "pytorch",
            "scikit-learn",
            "pandas",
            "numpy",
            "scipy",
            "bootstrap",
            "tailwind",
            "jquery",
            "hibernate",
            "nestjs",
        ]
    },
    # Databases
    **{
        k: "Database"
        for k in [
            "postgresql",
            "mysql",
            "mariadb",
            "sqlite",
            "mongodb",
            "redis",
            "elasticsearch",
            "oracle",
            "mssql",
            "firebird",
            "ibexpert",
            "dynamodb",
            "cassandra",
            "neo4j",
        ]
    },
    # Cloud & Infrastructure
    **{
        k: "Cloud"
        for k in [
            "aws",
            "azure",
            "google cloud",
            "gcp",
            "heroku",
            "digitalocean",
            "cloudflare",
            "vercel",
            "netlify",
            "s3",
            "ec2",
            "lambda",
            "azure ad",
        ]
    },
    # DevOps & Tools
    **{
        k: "DevOps"
        for k in [
            "docker",
            "kubernetes",
            "terraform",
            "ansible",
            "jenkins",
            "github actions",
            "gitlab ci",
            "ci/cd",
            "git",
            "linux",
            "ubuntu",
            "debian",
            "vmware",
            "hyper-v",
            "vagrant",
            "nginx",
            "apache",
            "prtg",
            "nagios",
            "zabbix",
        ]
    },
    # CRM & Sales Tools
    **{
        k: "CRM & Sales"
        for k in [
            "hubspot",
            "salesforce",
            "pipedrive",
            "zoho",
            "freshsales",
            "crm",
            "consultative selling",
            "business development",
            "b2b",
            "b2c",
            "gtm-strategie",
            "gtm strategie",
            "pipeline-design",
            "pipeline design",
            "lead-scoring",
            "lead scoring",
            "follow-ups",
            "closing",
            "cold calling",
            "account management",
            "key account",
            "saas",
            "outbound",
            "inbound",
            "upselling",
            "cross-selling",
            "wirtschaftliche argumentation",
            "demo",
            "quota",
        ]
    },
    # Healthcare IT
    **{
        k: "Healthcare IT"
        for k in [
            "hl7",
            "fhir",
            "dicom",
            "his",
            "kis",
            "lis",
            "roche",
            "siemens healthineers",
            "meditech",
            "sap healthcare",
            "orbis",
        ]
    },
    # Office & Productivity
    **{
        k: "Office & Productivity"
        for k in [
            "microsoft office",
            "excel",
            "word",
            "powerpoint",
            "outlook",
            "teams",
            "sharepoint",
            "confluence",
            "jira",
            "notion",
            "trello",
            "asana",
            "slack",
            "google workspace",
            "adobe",
            "adobe creative suite",
            "autocad",
            "sap",
            "sage",
            "active directory",
            "sophos",
            "wordpress",
            "seo",
            "google analytics",
        ]
    },
    # Soft Skills
    **{
        k: "Soft Skill"
        for k in [
            "projektmanagement",
            "project management",
            "teamarbeit",
            "teamwork",
            "kommunikation",
            "communication",
            "führung",
            "leadership",
            "präsentation",
            "presentation",
            "problemlösung",
            "problem solving",
            "agile",
            "scrum",
            "kanban",
            "zeitmanagement",
            "time management",
            "selbstorganisation",
            "stakeholder",
            "verhandlung",
            "negotiation",
            "wachstumsunternehmen",
        ]
    },
}


def _categorize_skill(name: str) -> str | None:
    """Map skill name to category using keyword table."""
    key = name.lower().strip()
    if key in _SKILL_CATEGORIES:
        return _SKILL_CATEGORIES[key]
    # Partial match for compound names
    for keyword, cat in _SKILL_CATEGORIES.items():
        if keyword in key or key in keyword:
            return cat
    return "Other"


def _annotate_sources(result: LLMExtractedCV, pages: list[str]) -> None:
    """Assign source='cv_page_N' to items based on where their text appears."""
    if not pages:
        return

    def _find_page(text: str) -> str:
        if not text:
            return "llm"
        for i, page_text in enumerate(pages):
            if text.lower() in page_text.lower():
                return f"cv_page_{i + 1}"
        return "llm"

    for skill in result.skills:
        skill.source = _find_page(skill.name)
    for exp in result.work_experiences:
        exp.source = _find_page(exp.company)
    for edu in result.educations:
        edu.source = _find_page(edu.institution)


def _regex_fallback(raw_text: str, pages: list[str]) -> ParsedCV:
    """Regex-based extraction fallback when LLM is unavailable."""
    # ── Email ────────────────────────────────────────────────────────────────
    email_match = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", raw_text)

    # ── Phone: only match labelled fields or international/national patterns ─
    phone: str | None = None
    # 1. Labelled: "Tel:", "Telefon:", "Mobil:", "Phone:", etc.
    phone_labelled = re.search(
        r"(?:Tel(?:efon)?|Handy|Mobil(?:e)?|Phone|Fon)[.:\s]*([+\d][\d\s/\-\(\)\.]{6,22})",
        raw_text,
        re.IGNORECASE,
    )
    if phone_labelled:
        phone = re.sub(r"[\s]+", " ", phone_labelled.group(1)).strip()
    else:
        # 2. International format starting with +
        intl = re.search(r"(\+[\d][\d\s\-\(\)]{7,20})", raw_text)
        if intl:
            phone = re.sub(r"[\s]+", " ", intl.group(1)).strip()

    # ── Location: German PLZ (5 digits) + city ───────────────────────────────
    location: str | None = None
    plz_city = re.search(r"\b(\d{5})\s+([\w\-]+(?:\s[\w\-]+)?)\b", raw_text)
    if plz_city:
        location = f"{plz_city.group(1)} {plz_city.group(2)}"
    # Override with labelled field if present
    loc_labelled = re.search(
        r"(?:Wohnort|Standort|Ort|Stadt|Adresse|Location|City)[:\s]+([^\n,]{3,60})",
        raw_text,
        re.IGNORECASE,
    )
    if loc_labelled:
        candidate = loc_labelled.group(1).strip()
        # Remove embedded PLZ to get clean city name or keep full address
        if not re.search(r"\d{5}", candidate):
            location = candidate
        elif plz_city:
            location = f"{plz_city.group(1)} {plz_city.group(2)}"

    # ── Headline: look for job title after name block ─────────────────────────
    headline: str | None = None
    # Match labelled fields like "Berufsbezeichnung:", "Position:", "Stelle:"
    hl_labelled = re.search(
        r"(?:Berufsbezeichnung|Position|Stelle|Job(?:titel)?|Beruf|Title|Profession)[:\s]+([^\n]{3,120})",
        raw_text,
        re.IGNORECASE,
    )
    if hl_labelled:
        headline = hl_labelled.group(1).strip()

    # ── Skills ───────────────────────────────────────────────────────────────
    tech_keywords = [
        "Python",
        "FastAPI",
        "React",
        "TypeScript",
        "Docker",
        "PostgreSQL",
        "Redis",
        "AWS",
        "Kubernetes",
        "Java",
        "JavaScript",
        "Node.js",
        "SQL",
        "Git",
        "CI/CD",
        "REST",
        "GraphQL",
        "LangChain",
        "Machine Learning",
        "TensorFlow",
        "PyTorch",
        "Pandas",
        "NumPy",
        "Scikit-learn",
        "Flask",
        "Django",
        "Spring",
        "Angular",
        "Vue",
        "Next.js",
        "MongoDB",
        "Elasticsearch",
        "Kafka",
        "RabbitMQ",
        "Terraform",
        "Ansible",
        "Linux",
        "Bash",
        "C++",
        "C#",
        "Go",
        "Rust",
        "Kotlin",
        "Swift",
        "R",
        "Scala",
        "Spark",
        "Hadoop",
    ]
    skills = [
        ParsedSkill(name=kw, source="cv_regex")
        for kw in tech_keywords
        if re.search(r"\b" + re.escape(kw) + r"\b", raw_text, re.IGNORECASE)
    ]

    return ParsedCV(
        raw_text=raw_text,
        pages=pages,
        email=email_match.group(0) if email_match else None,
        phone=phone,
        location=location,
        headline=headline,
        skills=skills,
        confidence=0.3,
        parser_version="0.3-regex-fallback",
    )
