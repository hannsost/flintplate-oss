from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.models import Agent, AgentEvent, AgentRun, AgentVersion
from app.agents.schemas import AgentInput, AgentRead, RunRead, TaskAssignment
from app.automation.service import job_source
from app.jobs.models import JobPosting
from app.tasks.models import Task
from app.users.models import User
from app.workqueue.models import WorkItem
from app.workqueue.service import enqueue


async def member(db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID | None) -> User:
    user = await db.scalar(
        select(User)
        .where(
            User.id == user_id,
            User.tenant_id == tenant_id,
            User.is_active.is_(True),
            User.role.in_(["admin", "recruiter"]),
        )
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise HTTPException(
            403,
            "Verantwortliche, Auftraggeber und Prüfer müssen aktive HR-Mitglieder dieses Firmenbereichs sein.",
        )
    return user


async def agent_version(db: AsyncSession, agent: Agent) -> AgentVersion:
    version = await db.scalar(
        select(AgentVersion).where(
            AgentVersion.agent_id == agent.id, AgentVersion.version == agent.version
        )
    )
    if version is None:
        raise HTTPException(409, "Agentenversion fehlt.")
    return version


async def read_agent(db: AsyncSession, agent: Agent) -> AgentRead:
    version = await agent_version(db, agent)
    return AgentRead(
        id=agent.id,
        name=agent.name,
        owner_id=agent.owner_id,
        enabled=agent.enabled,
        version=agent.version,
        capability=version.capability,
        daily_task_limit=version.daily_task_limit,
        max_attempts=version.max_attempts,
        four_eyes=version.four_eyes,
    )


async def configure(db: AsyncSession, agent: Agent, data: AgentInput, actor: User) -> None:
    await member(db, agent.tenant_id, data.owner_id)
    agent.name, agent.owner_id, agent.enabled = data.name, data.owner_id, data.enabled
    db.add(
        AgentVersion(
            agent_id=agent.id,
            version=agent.version,
            capability=data.capability,
            daily_task_limit=data.daily_task_limit,
            max_attempts=data.max_attempts,
            four_eyes=data.four_eyes,
            created_by=actor.id,
        )
    )
    await db.flush()


def event(db: AsyncSession, run: AgentRun, actor: uuid.UUID | None, action: str) -> None:
    db.add(AgentEvent(run_id=run.id, actor_id=actor, action=action, run_version=run.version))


async def read_run(db: AsyncSession, run: AgentRun) -> RunRead:
    await db.flush()
    item = await db.get(WorkItem, run.work_item_id)
    if item is None:
        raise HTTPException(409, "Auftragszustand fehlt.")
    state = run.status
    if state == "queued" and item.status in {"dead", "cancelled", "running"}:
        state = {"dead": "failed", "cancelled": "cancelled", "running": "running"}[item.status]
    return RunRead.model_validate(
        {
            **{name: getattr(run, name, None) for name in RunRead.model_fields},
            "status": state,
            "queue_status": item.status,
            "attempts": item.attempts,
            "max_attempts": item.max_attempts,
            "last_error_code": item.last_error_code,
        }
    )


async def assign(db: AsyncSession, agent: Agent, actor: User, data: TaskAssignment) -> AgentRun:
    lock_key = int.from_bytes(
        hashlib.sha256(f"agent-request:{agent.tenant_id}:{data.request_key}".encode()).digest()[:8],
        signed=True,
    )
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    fingerprint = hashlib.sha256(data.model_dump_json(exclude={"request_key"}).encode()).hexdigest()
    existing = await db.scalar(
        select(AgentRun).where(
            AgentRun.tenant_id == agent.tenant_id, AgentRun.request_key == data.request_key
        )
    )
    if existing is not None:
        if (
            existing.agent_id != agent.id
            or existing.delegated_by != actor.id
            or existing.input_hash != fingerprint
        ):
            raise HTTPException(
                409, "Auftragsschlüssel wurde bereits für einen anderen Auftrag verwendet."
            )
        return existing
    if agent.version != data.expected_version:
        raise HTTPException(409, "Agent wurde geändert. Bitte neu laden.")
    if not agent.enabled:
        raise HTTPException(409, "Der Agent ist pausiert.")
    version = await agent_version(db, agent)
    owner = await member(db, agent.tenant_id, agent.owner_id)
    reviewer = await member(db, agent.tenant_id, data.reviewer_id)
    if version.four_eyes and reviewer.id == actor.id:
        raise HTTPException(422, "Die Vier-Augen-Prüfung benötigt eine andere Person.")
    if version.capability == "ai_job_brief" and not data.authorize_ai:
        raise HTTPException(
            422,
            "Die Übermittlung der Stellendaten an den eingerichteten KI-Dienst muss ausdrücklich freigegeben werden.",
        )
    if version.capability == "ai_job_brief":
        from app.config import get_settings

        if not get_settings().agents_external_ai_enabled:
            raise HTTPException(403, "Externe Agenten-KI ist vom Betreiber noch nicht freigegeben.")
    job = await db.scalar(
        select(JobPosting).where(
            JobPosting.id == data.job_id, JobPosting.tenant_id == agent.tenant_id
        )
    )
    if job is None or job.publication_status == "archived":
        raise HTTPException(404, "Bearbeitbare Stelle nicht gefunden.")
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    used = await db.scalar(
        select(func.count())
        .select_from(AgentRun)
        .where(AgentRun.agent_id == agent.id, AgentRun.created_at >= today)
    )
    if (used or 0) >= version.daily_task_limit:
        raise HTTPException(429, "Das tägliche Auftragslimit dieses Agenten ist erreicht (UTC).")
    run_id = uuid.uuid4()
    item = await enqueue(
        db,
        kind="agent_task",
        key=str(run_id),
        payload={"run_id": str(run_id)},
        tenant_id=agent.tenant_id,
        max_attempts=version.max_attempts,
        concurrency_key=f"agent:{agent.id}",
    )
    task = Task(
        tenant_id=agent.tenant_id,
        assigned_to=None,
        assigned_agent_id=agent.id,
        assigned_by=actor.id,
        title=data.title,
        description=data.instructions,
        status="in_progress",
    )
    db.add(task)
    await db.flush()
    run = AgentRun(
        id=run_id,
        tenant_id=agent.tenant_id,
        agent_id=agent.id,
        agent_version_id=version.id,
        task_id=task.id,
        work_item_id=item.id,
        job_id=job.id,
        job_version=job.version,
        delegated_by=actor.id,
        delegated_auth_version=actor.auth_version,
        owner_auth_version=owner.auth_version,
        reviewer_id=reviewer.id,
        reviewer_auth_version=reviewer.auth_version,
        request_key=data.request_key,
        input_hash=fingerprint,
        source={**job_source(job), "instructions": data.instructions, "task_title": data.title},
    )
    if version.capability == "ai_job_brief":
        from app.agents.execution import provider_fingerprint

        run.source = {**run.source, "provider_fingerprint": provider_fingerprint()}
    db.add(run)
    await db.flush()
    event(db, run, actor.id, "assigned")
    return run


async def authority(
    db: AsyncSession, run: AgentRun, *, lock: bool = False
) -> tuple[Agent, AgentVersion]:
    from app.admin.models import Customer

    query = select(Agent).where(Agent.id == run.agent_id)
    if lock:
        query = query.with_for_update()
    agent = await db.scalar(query.execution_options(populate_existing=True))
    spec = await db.get(AgentVersion, run.agent_version_id)
    if (
        agent is None
        or spec is None
        or not agent.enabled
        or agent.version != spec.version
        or agent.tenant_id != run.tenant_id
    ):
        raise HTTPException(409, "Agent pausiert oder Konfiguration geändert.")
    customer = await db.get(Customer, run.tenant_id, populate_existing=True)
    if (
        customer is None
        or customer.status not in {"active", "trial"}
        or (
            customer.status == "trial"
            and customer.trial_ends_at
            and customer.trial_ends_at <= datetime.now(UTC)
        )
    ):
        raise HTTPException(403, "Firmenbereich nicht aktiv.")
    owner = await member(db, run.tenant_id, agent.owner_id)
    actor = await member(db, run.tenant_id, run.delegated_by)
    reviewer = await member(db, run.tenant_id, run.reviewer_id)
    if (
        owner.auth_version != run.owner_auth_version
        or actor.auth_version != run.delegated_auth_version
        or reviewer.auth_version != run.reviewer_auth_version
    ):
        raise HTTPException(403, "Zugangsberechtigung wurde seit der Beauftragung geändert.")
    job = await db.scalar(
        select(JobPosting).where(JobPosting.id == run.job_id, JobPosting.tenant_id == run.tenant_id)
    )
    if job is None or job.version != run.job_version or job.publication_status == "archived":
        raise HTTPException(409, "Stelle wurde seit der Beauftragung geändert.")
    if spec.capability == "ai_job_brief":
        from app.agents.execution import provider_fingerprint
        from app.config import get_settings

        if (
            not get_settings().agents_external_ai_enabled
            or run.source.get("provider_fingerprint") != provider_fingerprint()
        ):
            raise HTTPException(
                403, "KI-Dienst wurde seit der Beauftragung gesperrt oder geändert."
            )
    return agent, spec
