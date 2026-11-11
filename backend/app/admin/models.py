"""Admin / Multi-Tenant Hub models.

customers       – Tenant registry (Zeitarbeitsunternehmen, Recruiter-Agenturen, Solo-Recruiter)
customer_modules – Feature-Flag matrix: which modules are enabled per tenant
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Customer(Base):
    """Tenant / Kunde der palmscout-Plattform."""

    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)

    # zeitarbeit | recruiter_agency | solo_recruiter
    type: Mapped[str] = mapped_column(String(50), nullable=False, default="recruiter_agency")

    # free | starter | professional | enterprise
    plan: Mapped[str] = mapped_column(String(50), nullable=False, default="starter")

    # trial | active | suspended | churned
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="trial")

    # Contact
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="DE")

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Stripe Billing (Sprint 2.3)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, unique=True
    )

    # White-Label / Custom-Domain (Sprint 2.6)
    custom_domain: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    primary_color: Mapped[str | None] = mapped_column(String(7), nullable=True)  # e.g. "#2563eb"
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    brand_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    branding_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Lifecycle
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    contract_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    contract_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CustomerModule(Base):
    """Feature-Flag: welche Module sind für einen Kunden aktiviert."""

    __tablename__ = "customer_modules"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    customer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Module keys (slugs):
    # ai_cv_parser | ai_cover_letter | ai_interview_prep | ai_linkedin_post
    # map_view | job_scraper_import | kanban_pipeline | interview_scheduling
    # analytics_advanced | content_kit | zeitarbeit_pool | partner_portal
    module_key: Mapped[str] = mapped_column(String(100), nullable=False)

    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # None = unbegrenzt; Int = monatliches Limit (z.B. AI-Calls)
    usage_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    usage_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("customer_id", "module_key", name="uq_customer_module"),)


# ── Module catalog (static, for reference) ────────────────────────────────────

MODULES: list[dict[str, str]] = [
    {"key": "ai_cv_parser", "name": "KI CV-Parser", "category": "ai"},
    {"key": "ai_cover_letter", "name": "KI Anschreiben", "category": "ai"},
    {"key": "ai_interview_prep", "name": "KI Interview-Vorbereitung", "category": "ai"},
    {"key": "ai_linkedin_post", "name": "KI LinkedIn-Posts", "category": "ai"},
    {"key": "map_view", "name": "Kartenansicht", "category": "core"},
    {"key": "job_scraper_import", "name": "Job-Scraper Import", "category": "integration"},
    {"key": "kanban_pipeline", "name": "Kanban Pipeline", "category": "core"},
    {"key": "interview_scheduling", "name": "Interview-Planung", "category": "core"},
    {"key": "analytics_advanced", "name": "Analytics (Erweitert)", "category": "analytics"},
    {"key": "content_kit", "name": "Content Kit", "category": "ai"},
    {"key": "zeitarbeit_pool", "name": "Zeitarbeiter-Pool", "category": "core"},
    {"key": "partner_portal", "name": "Partner-Portal", "category": "integration"},
    {"key": "org_charts", "name": "Organigramme", "category": "core"},
    {"key": "dms", "name": "Dokumenten-Management", "category": "core"},
]
