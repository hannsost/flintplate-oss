"""Team management endpoints (Sprint 4.4).

Admin endpoints: POST/PATCH/DELETE require admin role.
Read endpoints: any recruiter in the tenant can read.

Mounted at /teams
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.admin.models import Customer
from app.dependencies import AdminUser, DBSession, RecruiterUser
from app.teams.models import TEAM_MEMBER_ROLES, Team, TeamMember
from app.teams.schemas import (
    MyTeamRead,
    TeamCreate,
    TeamMemberAdd,
    TeamMemberRead,
    TeamMemberUpdate,
    TeamRead,
    TeamUpdate,
    TeamWithMembers,
)
from app.teams.service import require_team

router = APIRouter()


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _enrich_members(members: list[TeamMember], db: DBSession) -> list[TeamMemberRead]:
    if not members:
        return []
    from app.users.models import User

    user_ids = [str(m.user_id) for m in members]
    rows = await db.execute(select(User).where(User.id.in_(user_ids)))
    users_map = {str(u.id): u for u in rows.scalars()}
    result = []
    for m in members:
        u = users_map.get(str(m.user_id))
        result.append(
            TeamMemberRead(
                id=m.id,
                team_id=m.team_id,
                user_id=m.user_id,
                role=m.role,
                joined_at=m.joined_at,
                full_name=u.full_name if u else None,
                email=u.email if u else "",
            )
        )
    return result


async def _team_to_read(team: Team, db: DBSession) -> TeamWithMembers:
    enriched = await _enrich_members(team.members, db)
    return TeamWithMembers(
        id=team.id,
        tenant_id=team.tenant_id,
        name=team.name,
        description=team.description,
        parent_team_id=team.parent_team_id,
        is_active=team.is_active,
        created_at=team.created_at,
        updated_at=team.updated_at,
        member_count=len(team.members),
        members=enriched,
    )


# ── Read endpoints (recruiter+) ───────────────────────────────────────────────


@router.get("", response_model=list[TeamRead])
async def list_teams(user: RecruiterUser, db: DBSession) -> list[TeamRead]:
    rows = await db.execute(
        select(Team)
        .where(Team.tenant_id == user.tenant_id, Team.is_active == True)  # noqa: E712
        .order_by(Team.name)
    )
    teams = list(rows.scalars().all())

    # Count members per team in one query
    counts_rows = await db.execute(
        select(TeamMember.team_id, func.count(TeamMember.id))
        .where(TeamMember.team_id.in_([t.id for t in teams]))
        .group_by(TeamMember.team_id)
    )
    counts = {str(tid): cnt for tid, cnt in counts_rows.all()}

    return [
        TeamRead(
            id=t.id,
            tenant_id=t.tenant_id,
            name=t.name,
            description=t.description,
            parent_team_id=t.parent_team_id,
            is_active=t.is_active,
            created_at=t.created_at,
            updated_at=t.updated_at,
            member_count=counts.get(str(t.id), 0),
        )
        for t in teams
    ]


@router.get("/mine", response_model=list[MyTeamRead])
async def my_teams(user: RecruiterUser, db: DBSession) -> list[MyTeamRead]:
    """Teams the current user belongs to."""
    rows = await db.execute(
        select(TeamMember, Team)
        .join(Team, TeamMember.team_id == Team.id)
        .where(
            TeamMember.user_id == user.id,
            Team.tenant_id == user.tenant_id,
            Team.is_active == True,  # noqa: E712
        )
    )
    results = rows.all()

    # Count members per team
    team_ids = [str(r.Team.id) for r in results]
    if not team_ids:
        return []
    counts_rows = await db.execute(
        select(TeamMember.team_id, func.count(TeamMember.id))
        .where(TeamMember.team_id.in_(team_ids))
        .group_by(TeamMember.team_id)
    )
    counts = {str(tid): cnt for tid, cnt in counts_rows.all()}

    return [
        MyTeamRead(
            id=r.Team.id,
            name=r.Team.name,
            role=r.TeamMember.role,
            member_count=counts.get(str(r.Team.id), 0),
        )
        for r in results
    ]


@router.get("/{team_id}", response_model=TeamWithMembers)
async def get_team(team_id: UUID, user: RecruiterUser, db: DBSession) -> TeamWithMembers:
    row = await db.execute(select(Team).where(Team.id == team_id, Team.tenant_id == user.tenant_id))
    team = row.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team nicht gefunden")
    return await _team_to_read(team, db)


# ── Write endpoints (admin only) ─────────────────────────────────────────────


@router.post("", response_model=TeamWithMembers, status_code=201)
async def create_team(body: TeamCreate, user: AdminUser, db: DBSession) -> TeamWithMembers:
    if user.tenant_id is None:
        raise HTTPException(status_code=403, detail="Keine Organisation zugewiesen.")
    if body.parent_team_id:
        await require_team(db, user.tenant_id, body.parent_team_id)

    team = Team(
        tenant_id=user.tenant_id,
        name=body.name,
        description=body.description,
        parent_team_id=body.parent_team_id,
    )
    db.add(team)
    await db.flush()
    await db.refresh(team)
    await db.commit()
    await db.refresh(team)
    return await _team_to_read(team, db)


@router.patch("/{team_id}", response_model=TeamWithMembers)
async def update_team(
    team_id: UUID, body: TeamUpdate, user: AdminUser, db: DBSession
) -> TeamWithMembers:
    row = await db.execute(select(Team).where(Team.id == team_id, Team.tenant_id == user.tenant_id))
    team = row.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team nicht gefunden")

    changes = body.model_dump(exclude_unset=True)
    if any(changes.get(field, True) is None for field in ("name", "is_active")):
        raise HTTPException(status_code=422, detail="Name und Aktivstatus dürfen nicht leer sein.")
    if body.parent_team_id:
        # Serialize hierarchy changes within an organization to prevent concurrent cycles.
        await db.execute(select(Customer.id).where(Customer.id == user.tenant_id).with_for_update())
        seen = {team.id}
        current: UUID | None = body.parent_team_id
        while current is not None:
            if current in seen:
                raise HTTPException(
                    status_code=422, detail="Die Teamhierarchie darf keinen Kreis enthalten."
                )
            seen.add(current)
            parent = await require_team(db, user.tenant_id, current)
            current = parent.parent_team_id
    for field, value in changes.items():
        setattr(team, field, value)
    team.updated_at = datetime.now()

    await db.commit()
    await db.refresh(team)
    return await _team_to_read(team, db)


@router.delete("/{team_id}", status_code=204)
async def delete_team(team_id: UUID, user: AdminUser, db: DBSession) -> None:
    row = await db.execute(select(Team).where(Team.id == team_id, Team.tenant_id == user.tenant_id))
    team = row.scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team nicht gefunden")
    # Soft-delete: set is_active = False
    team.is_active = False
    team.updated_at = datetime.now()
    await db.commit()


# ── Member management (admin only) ───────────────────────────────────────────


@router.post("/{team_id}/members", response_model=TeamMemberRead, status_code=201)
async def add_member(
    team_id: UUID, body: TeamMemberAdd, user: AdminUser, db: DBSession
) -> TeamMemberRead:
    from app.users.models import User

    if body.role not in TEAM_MEMBER_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {TEAM_MEMBER_ROLES}")

    # Verify team belongs to tenant
    t_row = await db.execute(
        select(Team).where(Team.id == team_id, Team.tenant_id == user.tenant_id)
    )
    if not t_row.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Team nicht gefunden")

    # Verify user belongs to tenant
    u_row = await db.execute(
        select(User).where(User.id == body.user_id, User.tenant_id == user.tenant_id)
    )
    target_user = u_row.scalar_one_or_none()
    if not target_user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")

    # Check duplicate
    existing = await db.execute(
        select(TeamMember).where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == body.user_id,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Benutzer ist bereits Teammitglied")

    member = TeamMember(team_id=team_id, user_id=body.user_id, role=body.role)
    db.add(member)
    await db.flush()
    await db.refresh(member)
    await db.commit()

    return TeamMemberRead(
        id=member.id,
        team_id=member.team_id,
        user_id=member.user_id,
        role=member.role,
        joined_at=member.joined_at,
        full_name=target_user.full_name,
        email=target_user.email,
    )


@router.patch("/{team_id}/members/{user_id}", response_model=TeamMemberRead)
async def update_member_role(
    team_id: UUID, user_id: UUID, body: TeamMemberUpdate, user: AdminUser, db: DBSession
) -> TeamMemberRead:
    from app.users.models import User

    if body.role not in TEAM_MEMBER_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {TEAM_MEMBER_ROLES}")

    row = await db.execute(
        select(TeamMember)
        .join(Team, Team.id == TeamMember.team_id)
        .where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == user_id,
            Team.tenant_id == user.tenant_id,
        )
    )
    member = row.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")

    member.role = body.role
    await db.commit()
    await db.refresh(member)

    u_row = await db.execute(select(User).where(User.id == user_id))
    u = u_row.scalar_one_or_none()
    return TeamMemberRead(
        id=member.id,
        team_id=member.team_id,
        user_id=member.user_id,
        role=member.role,
        joined_at=member.joined_at,
        full_name=u.full_name if u else None,
        email=u.email if u else "",
    )


@router.delete("/{team_id}/members/{user_id}", status_code=204)
async def remove_member(team_id: UUID, user_id: UUID, user: AdminUser, db: DBSession) -> None:
    row = await db.execute(
        select(TeamMember)
        .join(Team, Team.id == TeamMember.team_id)
        .where(
            TeamMember.team_id == team_id,
            TeamMember.user_id == user_id,
            Team.tenant_id == user.tenant_id,
        )
    )
    member = row.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=404, detail="Mitglied nicht gefunden")
    await db.delete(member)
    await db.commit()
