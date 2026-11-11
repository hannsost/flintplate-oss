"""026 document_management_system

Revision ID: 026
Revises: 025
Create Date: 2026-03-26
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID

from alembic import op

revision = "026"
down_revision = "025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── doc_categories ────────────────────────────────────────────────────────
    op.create_table(
        "doc_categories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        ),  # NULL = global default
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("slug", sa.String(50), nullable=False),  # zeugnis | vertrag | ...
        sa.Column("color", sa.String(7), nullable=False, server_default="#6b7280"),
        sa.Column("icon", sa.String(10), nullable=False, server_default="📄"),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # ── documents ─────────────────────────────────────────────────────────────
    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        # File
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("file_url", sa.String(1000), nullable=False),
        sa.Column("mime_type", sa.String(100), nullable=False),
        sa.Column("file_size", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("checksum", sa.String(64), nullable=True),  # SHA-256
        # Categorisation
        sa.Column(
            "category_id",
            UUID(as_uuid=True),
            sa.ForeignKey("doc_categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("tags", JSONB, nullable=True),  # ["tag1","tag2"]
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_template", sa.Boolean, nullable=False, server_default="false"),
        # Entity link
        # candidate | job_posting | placement | application | customer | null
        sa.Column("linked_entity_type", sa.String(50), nullable=True),
        sa.Column("linked_entity_id", UUID(as_uuid=True), nullable=True),
        # Versioning
        sa.Column("version_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column(
            "parent_document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("is_latest_version", sa.Boolean, nullable=False, server_default="true"),
        # Visibility
        sa.Column(
            "visibility", sa.String(20), nullable=False, server_default="tenant"
        ),  # private|tenant|share_link
        sa.Column("share_token", sa.String(64), nullable=True, unique=True),
        sa.Column("share_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("share_password_hash", sa.String(255), nullable=True),
        # Expiry tracking
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_reminder_days", sa.Integer, nullable=False, server_default="30"),
        # Processing (OCR + thumbnail)
        sa.Column("ocr_text", sa.Text, nullable=True),
        sa.Column("thumbnail_url", sa.String(1000), nullable=True),
        sa.Column(
            "processing_status", sa.String(20), nullable=False, server_default="pending"
        ),  # pending|done|failed
        # Full-text search vector (updated by service after OCR)
        sa.Column("search_vector", TSVECTOR, nullable=True),
        # Lifecycle
        sa.Column(
            "status", sa.String(20), nullable=False, server_default="active"
        ),  # active|archived|deleted
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_documents_tenant_status", "documents", ["tenant_id", "status"])
    op.create_index(
        "ix_documents_linked_entity", "documents", ["linked_entity_type", "linked_entity_id"]
    )
    op.create_index("ix_documents_expires_at", "documents", ["expires_at"])
    op.create_index(
        "ix_documents_search_vector", "documents", ["search_vector"], postgresql_using="gin"
    )

    # ── doc_shares ────────────────────────────────────────────────────────────
    op.create_table(
        "doc_shares",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "shared_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("share_token", sa.String(64), nullable=False, unique=True),
        sa.Column("shared_with_email", sa.String(255), nullable=True),
        sa.Column(
            "access_type", sa.String(20), nullable=False, server_default="view"
        ),  # view|download|sign
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("accessed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # ── doc_activity ──────────────────────────────────────────────────────────
    op.create_table(
        "doc_activity",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    # ── doc_comments ──────────────────────────────────────────────────────────
    op.create_table(
        "doc_comments",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "document_id",
            UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("doc_comments")
    op.drop_table("doc_activity")
    op.drop_table("doc_shares")
    op.drop_table("documents")
    op.drop_table("doc_categories")
