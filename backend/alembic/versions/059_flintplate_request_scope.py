"""Keep client request IDs unique within their own venue, not across tenants."""

from __future__ import annotations

from alembic import op

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None

CONSTRAINTS = {
    "fp_usage_sessions": "uq_fp_usage_key",
    "fp_vouchers": "uq_fp_voucher_issue_key",
    "fp_emergencies": "uq_fp_emergency_key",
}


def upgrade() -> None:
    for table, name in CONSTRAINTS.items():
        op.drop_constraint(f"{table}_request_key_key", table, type_="unique")
        op.create_unique_constraint(name, table, ["venue_id", "request_key"])


def downgrade() -> None:
    # PostgreSQL deliberately rejects this downgrade if cross-venue duplicates
    # now exist; never silently discard or rewrite business request identities.
    for table, name in CONSTRAINTS.items():
        op.create_unique_constraint(f"{table}_request_key_key", table, ["request_key"])
        op.drop_constraint(name, table, type_="unique")
