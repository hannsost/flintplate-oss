# Tenant-Scoping Decision – Candidate Pool & Multi-Tenancy (T-1)

**Date:** 2026-09-03  
**Status:** IMPLEMENTED  
**Severity:** 🔴 Critical – DSGVO/Confidentiality

---

## Summary

All zeitarbeit-related data endpoints have been audited and updated to enforce strict **tenant-scoped** data isolation. The candidate pool (temporary workers in `TempWorkerAvailability`) is **tenant-scoped**, not global.

---

## Decision: Tenant-Scoped Pool

### Choice
**Candidate pool is TENANT-SCOPED** – each recruiter sees only workers from their own organization/tenant.

### Rationale

1. **DSGVO Compliance**  
   - Recruiters from different organizations must not see each other's workers' personal data (full names, locations, skills, availability history).
   - Temp workers are not "global talent" — they are managed contracts under a specific employer's AÜG compliance regime.

2. **Separation of Concerns**  
   - A recruiter in Tenant A has no business relationship with workers in Tenant B.
   - Separate pools prevent accidental data leaks and unauthorized matching.

3. **AÜG Compliance**  
   - German labor law (Arbeitnehmerüberlassungsgesetz) tracks individual placements for each worker under specific staffing agencies.
   - Multi-tenant platform must segregate by organization to avoid mixing AÜG counters / compliance histories.

4. **Organizational Boundaries**  
   - B2B-SaaS design principle: strict isolation between customers.
   - If a global talent pool is needed later, it can be implemented as an **opt-in** cross-tenant feature with explicit consent.

---

## Implementation

### Affected Endpoints

| Endpoint | Model | Filter | Status |
|---|---|---|---|
| `GET /maps/data` | `WorkAssignment`, `TempWorkerAvailability` | `tenant_id` | ✅ FIXED |
| `GET /zeitarbeit/pool` | `TempWorkerAvailability` | `tenant_id` (via User) | ✅ FIXED |
| `GET /zeitarbeit/canvas/pool` | `TempWorkerAvailability` | `tenant_id` (via User) | ✅ FIXED |
| `GET /zeitarbeit/assignments` | `WorkAssignment` | `recruiter_id` (scoped by tenant via recruiter) | ✅ VERIFIED |
| `GET /zeitarbeit/time-entries/*` | `TimeEntry` | `tenant_id` | ✅ VERIFIED |
| `GET /jobs/recruiter/candidates` | `CandidateProfile`, `User` | `tenant_id` | ✅ FIXED |
| `GET /payroll/*` | `PayStub` | `tenant_id` | ✅ VERIFIED |
| `GET /equipment/*` | `EquipmentItem`, `EquipmentAssignment` | `tenant_id` | ✅ VERIFIED |
| `GET /tasks/*` | `Task` | `tenant_id` | ✅ VERIFIED |
| `GET /absences/*` | `Absence` | `tenant_id` | ✅ VERIFIED |
| `GET /zeitarbeit/messages` | `MessageThread` | `tenant_id` | ✅ VERIFIED |

### Database Schema Requirements

- ✅ `WorkAssignment.tenant_id` – indexed, enforced
- ✅ `User.tenant_id` – indexed, allows NULL for cross-tenant candidates
- ✅ Service queries filter by `User.tenant_id` when loading `TempWorkerAvailability`
- ✅ `Disposition` joins via `WorkAssignment.tenant_id` for isolation

---

## Future Considerations

### Option 1: Global Talent Marketplace (Later)
If a future sprint requires cross-tenant candidate visibility:
1. Add `TempWorkerAvailability.visibility` enum: `tenant_only` | `marketplace` | `private`
2. Update pool queries to filter by visibility level
3. Require explicit opt-in from both recruiter and worker
4. Add audit logging for all cross-tenant data access

### Option 2: Staffing Agency Mode
If the platform pivots to support staffing agencies (one tenant manages multiple customer accounts):
1. Add `WorkAssignment.customer_organization_id` (separate from tenant)
2. Create role hierarchy: staffing agency recruiter can see all their customer accounts
3. Segment pools by visibility policy

---

## Regression Tests

File: `backend/tests/test_tenant_scoping.py`

Tests verify:
- ✅ Recruiter A cannot see Tenant B's assignments on `/maps/data`
- ✅ Recruiter A cannot see Tenant B's workers on `/maps/data`
- ✅ Pool endpoint (`/zeitarbeit/pool`) returns only this tenant's workers
- ✅ Assignments list is scoped by tenant
- ✅ Dispositions do not leak across tenants
- ✅ Cross-tenant access is blocked

Run tests:
```bash
docker compose exec backend pytest backend/tests/test_tenant_scoping.py -xvs
```

---

## Incident Background (T-1)

**Symptom:** `GET /maps/data` returned the same 4 assignments for EVERY tenant (recruiter from Tenant A saw Tenant B's data).

**Root Cause:** Service functions did not accept/filter by `tenant_id` parameter.

**Fix Strategy:**
1. Add `tenant_id` parameter to service functions
2. Join with User model when `TempWorkerAvailability` lacks `tenant_id`
3. Filter all dispositions, assignments, and workers by recruiter's `current_user.tenant_id`
4. Add regression tests

---

## Sign-Off

- ✅ All identified endpoints audited
- ✅ Tenant-scoping applied to critical data paths
- ✅ Regression test suite created
- ✅ Decision documented for future feature work
