"""Pipeline Builder – konfigurierbare Stages (PalmSCOUT MVP 2)

Revision ID: 016
Revises: 015
Create Date: 2026-03-23
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None

# Standard-Stages passend zur bestehenden ApplicationStatus-Enum
_DEFAULT_STAGES = [
    (0, "Recherche", "bg-gray-100", False),
    (1, "Beworben", "bg-blue-100", False),
    (2, "Screening", "bg-yellow-100", False),
    (3, "Interview", "bg-purple-100", False),
    (4, "Angebot", "bg-emerald-100", False),
    (5, "Abgelehnt", "bg-red-100", True),
    (6, "Zurückgezogen", "bg-gray-200", True),
]

# Mapping: ApplicationStatus-Wert → Stage-Position
_STATUS_POSITION = {
    "research": 0,
    "applied": 1,
    "screening": 2,
    "interview": 3,
    "offer": 4,
    "rejected": 5,
    "withdrawn": 6,
}


def upgrade() -> None:
    # 1. pipeline_templates
    op.create_table(
        "pipeline_templates",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "recruiter_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "company_id",
            UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index("ix_pipeline_templates_recruiter_id", "pipeline_templates", ["recruiter_id"])

    # 2. pipeline_stages
    op.create_table(
        "pipeline_stages",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "template_id",
            UUID(as_uuid=True),
            sa.ForeignKey("pipeline_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("color", sa.String(30), nullable=True),
        sa.Column("is_terminal", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("on_enter_actions", JSONB(), nullable=True),
        sa.Column("sla_hours", sa.Integer(), nullable=True),
        sa.Column("sla_escalate_to", sa.String(100), nullable=True),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approver_role", sa.String(50), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("template_id", "position", name="uq_pipeline_stage_position"),
    )
    op.create_index("ix_pipeline_stages_template_id", "pipeline_stages", ["template_id"])

    # 3. application_stage_assignments
    op.create_table(
        "application_stage_assignments",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "application_id",
            UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "stage_id",
            UUID(as_uuid=True),
            sa.ForeignKey("pipeline_stages.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "entered_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_application_stage_assignments_application_id",
        "application_stage_assignments",
        ["application_id"],
    )
    op.create_index(
        "ix_application_stage_assignments_stage_id", "application_stage_assignments", ["stage_id"]
    )

    # 4. application_stage_history
    op.create_table(
        "application_stage_history",
        sa.Column(
            "id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column(
            "application_id",
            UUID(as_uuid=True),
            sa.ForeignKey("applications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "from_stage_id",
            UUID(as_uuid=True),
            sa.ForeignKey("pipeline_stages.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "to_stage_id",
            UUID(as_uuid=True),
            sa.ForeignKey("pipeline_stages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "changed_by",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "changed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_application_stage_history_application_id",
        "application_stage_history",
        ["application_id"],
    )
    op.create_index(
        "ix_application_stage_history_changed_at", "application_stage_history", ["changed_at"]
    )

    # 5. Seed default system template + stages
    conn = op.get_bind()

    # Insert system template (recruiter_id = NULL)
    result = conn.execute(sa.text("""
            INSERT INTO pipeline_templates (id, recruiter_id, name, is_default)
            VALUES (gen_random_uuid(), NULL, 'Standard-Pipeline', TRUE)
            RETURNING id
        """))
    template_id = result.fetchone()[0]

    # Insert stages
    stage_ids: dict[int, str] = {}
    for position, name, color, is_terminal in _DEFAULT_STAGES:
        res = conn.execute(
            sa.text("""
                INSERT INTO pipeline_stages (id, template_id, name, position, color, is_terminal)
                VALUES (gen_random_uuid(), :tid, :name, :pos, :color, :terminal)
                RETURNING id
            """),
            {
                "tid": template_id,
                "name": name,
                "pos": position,
                "color": color,
                "terminal": is_terminal,
            },
        )
        stage_ids[position] = str(res.fetchone()[0])

    # 6. Backfill application_stage_assignments from existing applications
    apps = conn.execute(
        sa.text("SELECT id, status FROM applications WHERE status IS NOT NULL")
    ).fetchall()

    for app_id, status_val in apps:
        position = _STATUS_POSITION.get(str(status_val), 0)
        stage_id = stage_ids[position]
        conn.execute(
            sa.text("""
                INSERT INTO application_stage_assignments (id, application_id, stage_id)
                VALUES (gen_random_uuid(), :app_id, :stage_id)
                ON CONFLICT DO NOTHING
            """),
            {"app_id": str(app_id), "stage_id": stage_id},
        )


def downgrade() -> None:
    op.drop_index("ix_application_stage_history_changed_at", "application_stage_history")
    op.drop_index("ix_application_stage_history_application_id", "application_stage_history")
    op.drop_table("application_stage_history")
    op.drop_index("ix_application_stage_assignments_stage_id", "application_stage_assignments")
    op.drop_index(
        "ix_application_stage_assignments_application_id", "application_stage_assignments"
    )
    op.drop_table("application_stage_assignments")
    op.drop_index("ix_pipeline_stages_template_id", "pipeline_stages")
    op.drop_table("pipeline_stages")
    op.drop_index("ix_pipeline_templates_recruiter_id", "pipeline_templates")
    op.drop_table("pipeline_templates")
