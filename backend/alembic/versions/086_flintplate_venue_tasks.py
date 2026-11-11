"""Versioned venue assignments on existing human tasks, with immutable commands.

Revision ID: 086
Revises: 085
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "086"
down_revision = "085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("require_completion_note", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "tasks", sa.Column("venue_id", sa.Uuid(), sa.ForeignKey("fp_venues.id"), nullable=True)
    )
    op.add_column("tasks", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.create_index("ix_tasks_venue_id", "tasks", ["venue_id"])
    op.create_unique_constraint("uq_tasks_venue_scope", "tasks", ["venue_id", "id"])
    op.create_check_constraint(
        "ck_tasks_venue_human",
        "tasks",
        "venue_id IS NULL OR (assigned_to IS NOT NULL AND assigned_agent_id IS NULL AND version > 0)",
    )
    op.create_table(
        "fp_task_commands",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("venue_id", sa.Uuid(), sa.ForeignKey("fp_venues.id"), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("request_key", sa.Uuid(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("actor_name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("note", sa.String(1000), nullable=False),
        sa.Column("before", JSONB(), nullable=True),
        sa.Column("after", JSONB(), nullable=False),
        sa.UniqueConstraint("venue_id", "request_key", name="uq_fp_task_command_key"),
        sa.UniqueConstraint("task_id", "version", name="uq_fp_task_command_version"),
        sa.ForeignKeyConstraint(["venue_id", "task_id"], ["tasks.venue_id", "tasks.id"]),
        sa.CheckConstraint("version > 0", name="ck_fp_task_command_version"),
        sa.CheckConstraint(
            "kind IN ('create','start','done','cancel','reopen','reassign','edit')",
            name="ck_fp_task_command_kind",
        ),
    )
    for column in ("id", "venue_id", "task_id"):
        op.create_index(f"ix_fp_task_commands_{column}", "fp_task_commands", [column])
    install_guards()


def install_guards() -> None:
    op.execute("""
      CREATE FUNCTION fp_task_state(value jsonb) RETURNS jsonb LANGUAGE sql STABLE AS $$
        SELECT jsonb_build_object('id',value->>'id','venue_id',value->>'venue_id',
          'title',value->>'title','description',value->>'description',
          'assigned_to',value->>'assigned_to','assigned_by',value->>'assigned_by',
          'due_at',extract(epoch FROM (value->>'due_at')::timestamptz),
          'priority',value->>'priority','require_completion_note',(value->>'require_completion_note')::boolean,'status',value->>'status','version',(value->>'version')::integer,
          'worker_note',value->>'worker_note','completed_at',extract(epoch FROM (value->>'completed_at')::timestamptz),
          'created_at',extract(epoch FROM (value->>'created_at')::timestamptz),
          'updated_at',extract(epoch FROM (value->>'updated_at')::timestamptz))
      $$
    """)
    op.execute("""
      CREATE FUNCTION fp_guard_venue_task() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE venue fp_venues;
      BEGIN
        IF TG_OP='DELETE' THEN
          IF OLD.venue_id IS NOT NULL THEN RAISE EXCEPTION 'Venue tasks cannot be deleted; cancel with evidence'; END IF;
          RETURN OLD;
        END IF;
        IF TG_OP='UPDATE' AND OLD.venue_id IS NOT NULL AND NEW.venue_id IS DISTINCT FROM OLD.venue_id THEN
          RAISE EXCEPTION 'Venue task authority cannot be detached'; END IF;
        IF NEW.venue_id IS NULL THEN RETURN NEW; END IF;
        SELECT * INTO venue FROM fp_venues WHERE id=NEW.venue_id FOR NO KEY UPDATE;
        IF venue.id IS NULL OR NEW.tenant_id IS DISTINCT FROM venue.tenant_id OR NEW.assigned_to IS NULL OR NEW.assigned_agent_id IS NOT NULL
          OR NEW.priority NOT IN ('low','medium','high','urgent') OR NEW.status NOT IN ('open','in_progress','done','cancelled')
          OR length(trim(NEW.title))<1 OR length(coalesce(NEW.description,''))>4000 OR length(coalesce(NEW.worker_note,''))>1000
          OR ((NEW.status='done') IS DISTINCT FROM (NEW.completed_at IS NOT NULL))
          OR NEW.due_date IS DISTINCT FROM (NEW.due_at AT TIME ZONE venue.timezone)::date
          THEN RAISE EXCEPTION 'Invalid venue task state'; END IF;
        IF TG_OP='INSERT' THEN
          IF NEW.version!=1 OR NEW.status!='open' OR NEW.worker_note IS NOT NULL THEN RAISE EXCEPTION 'Venue task must start open'; END IF;
        ELSE
          IF OLD.venue_id IS NULL OR NEW.version!=OLD.version+1 OR NEW.created_at IS DISTINCT FROM OLD.created_at OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id THEN
            RAISE EXCEPTION 'Venue task revision conflict'; END IF;
        END IF;
        IF TG_OP='INSERT' OR NEW.assigned_to IS DISTINCT FROM OLD.assigned_to THEN
          IF NOT EXISTS (SELECT 1 FROM users u JOIN fp_memberships m ON m.user_id=u.id WHERE u.id=NEW.assigned_to AND u.tenant_id=venue.tenant_id AND u.is_active AND m.venue_id=venue.id AND m.active AND m.role IN ('manager','service','kitchen')) THEN
            RAISE EXCEPTION 'Venue task assignee must be an active member'; END IF;
        END IF;
        RETURN NEW;
      END $$
    """)
    op.execute(
        "CREATE TRIGGER tasks_venue_guard BEFORE INSERT OR UPDATE OR DELETE ON tasks FOR EACH ROW EXECUTE FUNCTION fp_guard_venue_task()"
    )
    op.execute("""
      CREATE FUNCTION fp_guard_task_command() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE task tasks; previous fp_task_commands; role text; before_state jsonb; after_state jsonb; allowed text[];
      BEGIN
        IF TG_OP!='INSERT' THEN RAISE EXCEPTION 'Task commands are append-only'; END IF;
        SELECT * INTO task FROM tasks WHERE id=NEW.task_id AND venue_id=NEW.venue_id FOR UPDATE;
        SELECT m.role INTO role FROM fp_memberships m JOIN users u ON u.id=m.user_id JOIN fp_venues v ON v.id=m.venue_id
          WHERE m.venue_id=NEW.venue_id AND m.user_id=NEW.actor_id AND m.active AND u.is_active AND u.tenant_id=v.tenant_id;
        IF task.id IS NULL OR role IS NULL OR (NEW.kind NOT IN ('start','done') AND length(trim(NEW.note))<3) OR length(NEW.request_hash)!=64
          OR jsonb_typeof(NEW.after) IS DISTINCT FROM 'object' OR NOT(NEW.after ?& ARRAY['id','venue_id','title','description','assigned_to','assigned_by','due_at','priority','require_completion_note','status','version','worker_note','completed_at','created_at','updated_at'])
          THEN RAISE EXCEPTION 'Task command requires complete scoped evidence'; END IF;
        SELECT * INTO previous FROM fp_task_commands WHERE task_id=task.id ORDER BY version DESC LIMIT 1;
        IF NEW.version IS DISTINCT FROM coalesce(previous.version,0)+1 OR task.version IS DISTINCT FROM NEW.version THEN RAISE EXCEPTION 'Task command revision differs'; END IF;
        after_state := fp_task_state(NEW.after);
        IF after_state IS DISTINCT FROM fp_task_state(to_jsonb(task)) THEN RAISE EXCEPTION 'Task command differs from current task'; END IF;
        IF NEW.version=1 THEN
          IF NEW.kind!='create' OR NEW.before IS NOT NULL OR role!='manager' OR task.assigned_by IS DISTINCT FROM NEW.actor_id THEN RAISE EXCEPTION 'Task creation requires manager'; END IF;
        ELSE
          IF jsonb_typeof(NEW.before) IS DISTINCT FROM 'object' THEN RAISE EXCEPTION 'Task previous state missing'; END IF;
          before_state := fp_task_state(NEW.before);
          IF before_state IS DISTINCT FROM fp_task_state(previous.after) THEN RAISE EXCEPTION 'Task previous command differs'; END IF;
          IF NEW.kind IN ('start','done') THEN
            IF NEW.actor_id IS DISTINCT FROM task.assigned_to OR role NOT IN ('manager','service','kitchen') THEN RAISE EXCEPTION 'Only task assignee can confirm work'; END IF;
            IF (NEW.kind='start' AND (NEW.before->>'status' IS DISTINCT FROM 'open' OR task.status!='in_progress'))
              OR (NEW.kind='done' AND (NEW.before->>'status' NOT IN ('open','in_progress') OR task.status!='done'))
              OR task.worker_note IS DISTINCT FROM nullif(NEW.note,'') OR (NEW.kind='done' AND task.require_completion_note AND length(trim(NEW.note))<3) THEN RAISE EXCEPTION 'Task work transition differs'; END IF;
            allowed := ARRAY['version','updated_at','status','worker_note','completed_at'];
          ELSE
            IF role!='manager' THEN RAISE EXCEPTION 'Task management requires manager'; END IF;
            IF NEW.kind='reopen' THEN
              IF NEW.before->>'status' NOT IN ('done','cancelled') OR task.status!='open' THEN RAISE EXCEPTION 'Task reopen transition differs'; END IF;
              allowed := ARRAY['version','updated_at','status','worker_note','completed_at'];
            ELSE
              IF NEW.before->>'status' NOT IN ('open','in_progress') THEN RAISE EXCEPTION 'Task must be reopened first'; END IF;
              IF NEW.kind='cancel' THEN
                IF task.status!='cancelled' THEN RAISE EXCEPTION 'Task cancellation status differs'; END IF;
                allowed := ARRAY['version','updated_at','status','completed_at'];
              ELSIF NEW.kind='reassign' THEN
                IF task.assigned_to::text IS NOT DISTINCT FROM NEW.before->>'assigned_to' OR task.assigned_by IS DISTINCT FROM NEW.actor_id OR task.status!='open' THEN RAISE EXCEPTION 'Task reassignment differs'; END IF;
                allowed := ARRAY['version','updated_at','status','worker_note','completed_at','assigned_to','assigned_by'];
              ELSIF NEW.kind='edit' THEN allowed := ARRAY['version','updated_at','title','description','due_at','priority','require_completion_note'];
              ELSE RAISE EXCEPTION 'Unsupported task command'; END IF;
            END IF;
          END IF;
          IF (after_state-allowed) IS DISTINCT FROM (before_state-allowed) THEN RAISE EXCEPTION 'Task command changes unrelated fields'; END IF;
        END IF;
        RETURN NEW;
      END $$
    """)
    op.execute(
        "CREATE TRIGGER fp_task_commands_guard BEFORE INSERT OR UPDATE OR DELETE ON fp_task_commands FOR EACH ROW EXECUTE FUNCTION fp_guard_task_command()"
    )
    op.execute(
        "CREATE TRIGGER fp_task_commands_no_truncate BEFORE TRUNCATE ON fp_task_commands FOR EACH STATEMENT EXECUTE FUNCTION fp_guard_task_command()"
    )
    op.execute("""
      CREATE FUNCTION fp_require_task_command() RETURNS trigger LANGUAGE plpgsql AS $$
      DECLARE task tasks; command fp_task_commands; target uuid;
      BEGIN
        IF TG_TABLE_NAME='tasks' THEN target:=NEW.id; ELSE target:=NEW.task_id; END IF;
        SELECT * INTO task FROM tasks WHERE id=target;
        IF task.venue_id IS NULL THEN RETURN NEW; END IF;
        SELECT * INTO command FROM fp_task_commands WHERE task_id=task.id ORDER BY version DESC LIMIT 1;
        IF command.id IS NULL OR command.version IS DISTINCT FROM task.version OR fp_task_state(command.after) IS DISTINCT FROM fp_task_state(to_jsonb(task)) THEN
          RAISE EXCEPTION 'Venue task requires matching immutable command at commit'; END IF;
        RETURN NEW;
      END $$
    """)
    op.execute(
        "CREATE CONSTRAINT TRIGGER tasks_require_command AFTER INSERT OR UPDATE ON tasks DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fp_require_task_command()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER fp_task_commands_require_head AFTER INSERT ON fp_task_commands DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION fp_require_task_command()"
    )
    op.execute("""
      CREATE FUNCTION fp_block_task_truncate() RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN IF EXISTS(SELECT 1 FROM tasks WHERE venue_id IS NOT NULL) THEN RAISE EXCEPTION 'Venue task history must be retained'; END IF; RETURN NULL; END $$
    """)
    op.execute(
        "CREATE TRIGGER tasks_venue_no_truncate BEFORE TRUNCATE ON tasks FOR EACH STATEMENT EXECUTE FUNCTION fp_block_task_truncate()"
    )


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS(SELECT 1 FROM tasks WHERE venue_id IS NOT NULL) OR EXISTS(SELECT 1 FROM fp_task_commands)"
            )
        )
        .scalar_one()
    ):
        raise RuntimeError("Downgrade would erase immutable venue task evidence")
    op.execute("DROP TRIGGER tasks_venue_no_truncate ON tasks")
    op.execute("DROP FUNCTION fp_block_task_truncate()")
    op.execute("DROP TRIGGER tasks_require_command ON tasks")
    op.execute("DROP TRIGGER fp_task_commands_require_head ON fp_task_commands")
    op.execute("DROP FUNCTION fp_require_task_command()")
    op.execute("DROP TRIGGER tasks_venue_guard ON tasks")
    op.execute("DROP FUNCTION fp_guard_venue_task()")
    op.drop_table("fp_task_commands")
    op.execute("DROP FUNCTION fp_guard_task_command()")
    op.execute("DROP FUNCTION fp_task_state(jsonb)")
    op.drop_constraint("ck_tasks_venue_human", "tasks", type_="check")
    op.drop_constraint("uq_tasks_venue_scope", "tasks", type_="unique")
    op.drop_index("ix_tasks_venue_id", table_name="tasks")
    op.drop_column("tasks", "require_completion_note")
    op.drop_column("tasks", "version")
    op.drop_column("tasks", "due_at")
    op.drop_column("tasks", "venue_id")
