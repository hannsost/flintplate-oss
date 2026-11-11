"""Provision the local API role after migrations, outside the API container.

The caller uses the migration identity. No URL, password, verifier or database
exception is printed. SQL identifiers are checked, and a SCRAM verifier keeps
the plaintext password out of PostgreSQL statement logs.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import os
import re
import secrets
import sys

import asyncpg
from sqlalchemy.engine import make_url

APPEND_ONLY_TABLES = frozenset(
    {
        "fp_cancellation_requests",
        "fp_cancellation_decisions",
        "fp_cancellation_executions",
        "fp_cancellation_units",
        "fp_cancellation_acknowledgements",
        "fp_cancellation_checkout_acks",
        "fp_task_commands",
        "fp_service_commands",
        "fp_service_rounds",
        "fp_service_round_children",
        "fp_service_unit_assignments",
        "fp_payment_groups",
        "fp_payment_group_entries",
        "fp_payer_tip_entries",
        "fp_tip_run_sources",
        "fp_equal_split_plans",
        "fp_equal_split_parts",
        "fp_equal_split_part_payments",
        "fp_equal_split_plan_actions",
        "fp_order_operations",
        "fp_floor_layout_revisions",
        "fp_floor_layout_commands",
        "fp_labour_rate_revisions",
        "fp_delivery_confirmations",
        "fp_supplier_bonus_document_revisions",
        "fp_supplier_bonus_allocation_reversals",
        "fp_supplier_order_terms",
        "fp_supplier_bonus_agreements",
        "fp_supplier_bonus_statements",
        "fp_supplier_bonus_documents",
        "fp_supplier_bonus_allocations",
        "fp_events",
        "fp_cash_entries",
        "fp_voucher_entries",
        "fp_loyalty_entries",
        "fp_tip_runs",
        "fp_tip_shares",
        "fp_stock_operations",
        "fp_stock_movements",
        "fp_recipe_versions",
        "fp_prep_runs",
        "fp_haccp_records",
        "fp_hygiene_plan_versions",
        "fp_hygiene_plan_checks",
        "fp_partner_contracts",
        "fp_partner_terms",
        "fp_partner_postings",
        "fp_partner_events",
        "fp_partner_settlements",
        "fp_loan_accounts",
        "fp_loan_entries",
        "fp_reservation_resources",
        "fp_reservation_commands",
        "fp_station_commands",
        "fp_stock_reservations",
        "fp_stock_reservation_closures",
        "fp_supplier_prices",
        "fp_purchase_order_lines",
        "fp_purchase_receipts",
        "fp_purchase_invoice_lines",
    }
)
ALLOWED_DATABASES = frozenset({"flintplate", "flintplate_test"})


def identifier(value: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", value):
        raise ValueError("Unsupported database identifier")
    return f'"{value}"'


def scram_verifier(password: str) -> str:
    # setup-local creates ASCII hex passwords, avoiding SASLprep ambiguity.
    if len(password) < 32 or not password.isascii() or any(c.isspace() for c in password):
        raise ValueError("Runtime password must contain at least 32 ASCII characters")
    salt = secrets.token_bytes(16)
    iterations = 4096
    salted = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    client_key = hmac.digest(salted, b"Client Key", "sha256")
    stored_key = hashlib.sha256(client_key).digest()
    server_key = hmac.digest(salted, b"Server Key", "sha256")

    def encode(value: bytes) -> str:
        return base64.b64encode(value).decode("ascii")

    return f"SCRAM-SHA-256${iterations}:{encode(salt)}${encode(stored_key)}:{encode(server_key)}"


async def connect_owner(url_string: str) -> asyncpg.Connection:
    url = make_url(url_string)
    if url.database not in ALLOWED_DATABASES or url.username != "flintplate":
        raise ValueError("Administrative jobs require the isolated FlintPlate owner database")
    return await asyncpg.connect(
        host=url.host,
        port=url.port or 5432,
        user=url.username,
        password=url.password,
        database=url.database,
    )


async def provision_role(
    connection: asyncpg.Connection,
    *,
    password: str,
    role: str = "flintplate_runtime",
    schema: str = "public",
    lockdown_public: bool = True,
) -> None:
    """Apply privileges atomically, including tables added by the latest migration.

    Test callers use a unique role/schema and disable database-wide PUBLIC changes.
    The real job always revokes PUBLIC's database CREATE/TEMP and schema CREATE.
    """
    target = identifier(role)
    namespace = identifier(schema)
    database = await connection.fetchval("SELECT current_database()")
    owner = await connection.fetchval("SELECT current_user")
    if database not in ALLOWED_DATABASES or role == owner or not role.startswith("flintplate_"):
        raise ValueError("Refusing to provision outside the isolated runtime identity")
    verifier = scram_verifier(password)
    async with connection.transaction():
        await connection.execute("SELECT pg_advisory_xact_lock(77124073)")
        exists = await connection.fetchval("SELECT 1 FROM pg_roles WHERE rolname=$1", role)
        if not exists:
            await connection.execute(f"CREATE ROLE {target}")
        # DROP OWNED would drop objects. Fail safely if this dedicated role owns
        # anything, rather than transferring or destroying unexpected objects.
        owns_objects = await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_shdepend d JOIN pg_roles r ON r.oid=d.refobjid "
            "WHERE r.rolname=$1 AND d.deptype='o')",
            role,
        )
        if owns_objects:
            raise ValueError("Runtime role unexpectedly owns database objects")
        memberships = await connection.fetch(
            "SELECT p.rolname FROM pg_auth_members m JOIN pg_roles p ON p.oid=m.roleid "
            "JOIN pg_roles r ON r.oid=m.member WHERE r.rolname=$1",
            role,
        )
        for membership in memberships:
            await connection.execute(f"REVOKE {identifier(membership['rolname'])} FROM {target}")
        await connection.execute(
            f"ALTER ROLE {target} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
            f"NOINHERIT NOREPLICATION NOBYPASSRLS PASSWORD '{verifier}'"
        )
        await connection.execute(f"ALTER ROLE {target} RESET ALL")
        await connection.execute(f"ALTER ROLE {target} SET search_path = {namespace}, pg_catalog")
        # With no owned objects this only removes old grants, including column
        # grants and dangerous function permissions from earlier provisioning.
        await connection.execute(f"DROP OWNED BY {target} RESTRICT")
        if lockdown_public:
            await connection.execute(
                f"REVOKE CREATE, TEMPORARY ON DATABASE {identifier(database)} FROM PUBLIC"
            )
            await connection.execute(f"REVOKE CREATE ON SCHEMA {namespace} FROM PUBLIC")
        await connection.execute(f"GRANT CONNECT ON DATABASE {identifier(database)} TO {target}")
        await connection.execute(f"GRANT USAGE ON SCHEMA {namespace} TO {target}")
        # PUBLIC grants also apply to this role. Seal journal and migration
        # metadata explicitly instead of relying only on direct role revocations.
        tables = await connection.fetch(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE n.nspname=$1 AND c.relkind IN ('r','p','v','m','f') ORDER BY c.relname",
            schema,
        )
        for table in tables:
            name = table["relname"]
            qualified = f"{namespace}.{identifier(name)}"
            if name == "alembic_version":
                await connection.execute(f"REVOKE ALL ON TABLE {qualified} FROM PUBLIC")
                continue
            if name in APPEND_ONLY_TABLES:
                await connection.execute(f"REVOKE ALL ON TABLE {qualified} FROM PUBLIC")
                privileges = "SELECT, INSERT"
            elif name in {"fp_stock_lots", "fp_floor_layout_profiles"}:
                privileges = "SELECT, INSERT, UPDATE"
            else:
                privileges = "SELECT, INSERT, UPDATE, DELETE"
            await connection.execute(f"GRANT {privileges} ON TABLE {qualified} TO {target}")
        await connection.execute(
            f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {namespace} TO {target}"
        )
        # App trigger functions run as invoker. SECURITY DEFINER functions could
        # bypass the role boundary and require a separate explicit review.
        elevated_functions = await connection.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
            "WHERE n.nspname=$1 AND p.prosecdef AND has_function_privilege($2,p.oid,'EXECUTE'))",
            schema,
            role,
        )
        if elevated_functions:
            raise ValueError("Runtime can execute an unreviewed security-definer function")


async def main() -> None:
    connection = await connect_owner(os.environ["DATABASE_URL"])
    try:
        await provision_role(connection, password=os.environ["FLINTPLATE_RUNTIME_DB_PASSWORD"])
    finally:
        await connection.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (asyncpg.PostgresError, OSError, ValueError, KeyError):
        print(
            "Runtime-Provisionierung fehlgeschlagen; keine Zugangsdaten ausgegeben.",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    print("FlintPlate-Runtime-Rolle und Tabellenrechte vorbereitet.")
