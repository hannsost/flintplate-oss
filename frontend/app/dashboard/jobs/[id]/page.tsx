"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { recruiterApi, interviewScheduleApi, pipelineApi, ApiError } from "@/lib/api";
import type { JobPosting, CandidateMatch, RecruiterApplication, InterviewScheduleRead, PlacementRead, PipelineTemplateRead } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { InterviewModal } from "@/components/recruiter/InterviewModal";
import { ScorecardModal } from "@/components/recruiter/ScorecardModal";
import { PlaceModal } from "@/components/recruiter/PlaceModal";
import { CandidateProfileModal } from "@/components/recruiter/CandidateProfileModal";
import { normalizeSkills } from "@/lib/skills";
import { VermerkPanel } from "@/components/vermerke/VermerkPanel";

type Tab = "applications" | "pipeline";

function SkillBadge({ skill, matched }: { skill: string; matched: boolean }) {
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
        matched
          ? "bg-green-100 text-green-700 border border-green-200"
          : "bg-red-50 text-red-600 border border-red-200"
      }`}
    >
      {skill}
    </span>
  );
}

function GateBadge({ passed }: { passed: boolean }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${
        passed
          ? "bg-green-100 text-green-700"
          : "bg-gray-100 text-gray-500"
      }`}
    >
      {passed ? "✓ Qualifiziert" : "Unter Schwellenwert"}
    </span>
  );
}

export default function JobCandidatesPage() {
  const router = useRouter();
  const params = useParams();
  const jobId = params.id as string;

  const [job, setJob] = useState<JobPosting | null>(null);
  const [tab, setTab] = useState<Tab>("applications");

  // Applications tab
  const [applications, setApplications] = useState<RecruiterApplication[]>([]);
  const [appTotal, setAppTotal] = useState(0);

  // Pipeline tab
  const [candidates, setCandidates] = useState<CandidateMatch[]>([]);
  const [pipeTotal, setPipeTotal] = useState(0);

  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [tabLoading, setTabLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [interviewApp, setInterviewApp] = useState<RecruiterApplication | null>(null);
  const [schedules, setSchedules] = useState<Record<string, InterviewScheduleRead>>({});
  const [placeApp, setPlaceApp] = useState<RecruiterApplication | null>(null);
  const [placements, setPlacements] = useState<Record<string, PlacementRead>>({});
  const [scorecardCandidate, setScorecardCandidate] = useState<CandidateMatch | null>(null);
  const [pipelineTemplates, setPipelineTemplates] = useState<PipelineTemplateRead[]>([]);
  const [transitioningId, setTransitioningId] = useState<string | null>(null);
  const [profileUserId, setProfileUserId] = useState<string | null>(null);
  const [profileCandidateName, setProfileCandidateName] = useState<string | null>(null);

  const PAGE_SIZE = 20;

  const fetchApplications = useCallback(async (p: number) => {
    const token = auth.getAccess();
    if (!token) { router.push("/login"); return; }
    setTabLoading(true);
    try {
      const resp = await recruiterApi.getApplications(token, jobId, p, PAGE_SIZE);
      setApplications(resp.applications);
      setAppTotal(resp.total);
      setPage(p);

      // Load interview schedules for each application
      const newSchedules: Record<string, InterviewScheduleRead> = {};
      await Promise.allSettled(
        resp.applications.map(async (a) => {
          try {
            const s = await interviewScheduleApi.get(token!, a.id);
            if (s) newSchedules[a.id] = s;
          } catch { /* no schedule */ }
        })
      );
      setSchedules(newSchedules);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) router.push("/login");
    } finally {
      setTabLoading(false);
    }
  }, [jobId, router]);

  const fetchCandidates = useCallback(async (p: number) => {
    const token = auth.getAccess();
    if (!token) { router.push("/login"); return; }
    setTabLoading(true);
    try {
      const resp = await recruiterApi.getCandidates(token, jobId, p, PAGE_SIZE);
      setCandidates(resp.candidates);
      setPipeTotal(resp.total);
      setPage(p);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) router.push("/login");
      else setError("Kandidaten konnten nicht geladen werden.");
    } finally {
      setTabLoading(false);
    }
  }, [jobId, router]);

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) { router.push("/login"); return; }

    async function init() {
      try {
        const [jobsResp, templates] = await Promise.all([
          recruiterApi.listJobs(token!, 1, 100),
          pipelineApi.listTemplates(token!),
        ]);
        const found = jobsResp.jobs.find((j) => j.id === jobId);
        if (!found) { setError("Job nicht gefunden."); setLoading(false); return; }
        setJob(found);
        setPipelineTemplates(templates);
        await fetchApplications(1);
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) router.push("/login");
        else setError("Fehler beim Laden.");
      } finally {
        setLoading(false);
      }
    }
    init();
  }, [jobId, router, fetchApplications]);

  async function handleTabChange(t: Tab) {
    setTab(t);
    setPage(1);
    if (t === "pipeline") await fetchCandidates(1);
    else await fetchApplications(1);
  }

  async function handleStatusChange(appId: string, newStatus: string) {
    const token = auth.getAccess();
    if (!token) return;
    setUpdatingId(appId);
    try {
      await recruiterApi.updateApplicationStatus(token, jobId, appId, newStatus);
      setApplications((prev) =>
        prev.map((a) => a.id === appId ? { ...a, status: newStatus } : a)
      );
    } catch {
      alert("Status-Update fehlgeschlagen.");
    } finally {
      setUpdatingId(null);
    }
  }

  async function handleStageTransition(appId: string, toStageId: string) {
    const token = auth.getAccess();
    if (!token) return;
    setTransitioningId(appId);
    try {
      await pipelineApi.transition(token, { application_id: appId, to_stage_id: toStageId });
      await fetchApplications(page);
    } catch {
      alert("Stage-Wechsel fehlgeschlagen.");
    } finally {
      setTransitioningId(null);
    }
  }

  // Flatten all stages from all templates for the transition dropdown
  const allStages = pipelineTemplates.flatMap((t) =>
    t.stages.map((s) => ({ ...s, templateName: t.name }))
  );

  if (loading) {
    return (
      <>

        <div className="flex min-h-[60vh] items-center justify-center">
          <p className="text-gray-500">Lade Kandidaten…</p>
        </div>
      </>
    );
  }

  if (error) {
    return (
      <>

        <div className="flex min-h-[60vh] items-center justify-center">
          <p className="text-red-500">{error}</p>
        </div>
      </>
    );
  }

  const qualifiedCount = candidates.filter((c) => c.passed_gate).length;
  const activeTotal = tab === "applications" ? appTotal : pipeTotal;
  const totalPages = Math.ceil(activeTotal / PAGE_SIZE);

  const STATUS_OPTIONS = [
    { value: "applied", label: "Beworben" },
    { value: "screening", label: "Screening" },
    { value: "interview", label: "Interview" },
    { value: "offer", label: "Angebot" },
    { value: "rejected", label: "Abgelehnt" },
    { value: "withdrawn", label: "Zurückgezogen" },
  ];

  const STATUS_COLORS: Record<string, string> = {
    applied: "bg-blue-100 text-blue-700",
    screening: "bg-yellow-100 text-yellow-700",
    interview: "bg-purple-100 text-purple-700",
    offer: "bg-green-100 text-green-700",
    rejected: "bg-red-100 text-red-600",
    withdrawn: "bg-gray-100 text-gray-500",
  };

  return (
    <>

      <main className="mx-auto max-w-5xl px-4 py-8 space-y-6">
        {/* Header */}
        <div className="flex items-start justify-between gap-4">
          <div>
            <Link href="/dashboard" className="text-sm text-gray-500 hover:text-gray-700">
              ← Dashboard
            </Link>
            {job && (
              <>
                <h1 className="text-2xl font-bold text-gray-900 mt-1">{job.title}</h1>
                <p className="text-sm text-gray-500 mt-0.5">
                  {job.company}{job.location ? ` · ${job.location}` : ""}
                </p>
              </>
            )}
          </div>
          {job && (
            <Link href={`/dashboard/jobs/${job.id}/edit`}>
              <Button variant="outline" size="sm">Bearbeiten</Button>
            </Link>
          )}
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-4">
          <Card>
            <CardHeader className="pb-1">
              <CardTitle className="text-sm font-medium text-gray-500">Bewerbungen</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold text-gray-900">{appTotal}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-1">
              <CardTitle className="text-sm font-medium text-gray-500">Qualifiziert (&ge;50%)</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold text-green-600">{qualifiedCount}</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-1">
              <CardTitle className="text-sm font-medium text-gray-500">Alle Profile</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold text-gray-900">{pipeTotal}</p>
            </CardContent>
          </Card>
        </div>

        {/* Tab switcher */}
        <div className="flex gap-1 rounded-lg border border-gray-200 bg-gray-50 p-1 w-fit">
          {(["applications", "pipeline"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => handleTabChange(t)}
              className={`rounded-md px-4 py-1.5 text-sm font-medium transition-colors ${
                tab === t
                  ? "bg-white shadow-sm text-gray-900"
                  : "text-gray-500 hover:text-gray-700"
              }`}
            >
              {t === "applications" ? `Bewerbungen (${appTotal})` : `Pipeline (${pipeTotal})`}
            </button>
          ))}
        </div>

        {/* Required skills */}
        {job && job.required_skills.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {normalizeSkills(job.required_skills).map((s) => (
              <span
                key={s}
                className="rounded-full bg-blue-50 border border-blue-200 px-2.5 py-0.5 text-xs text-blue-700"
              >
                {s}
              </span>
            ))}
          </div>
        )}

        {/* Content */}
        {tabLoading ? (
          <div className="flex justify-center py-12">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
          </div>
        ) : tab === "applications" ? (
          applications.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <p className="text-gray-500">Noch keine Bewerbungen eingegangen.</p>
                <p className="text-sm text-gray-400 mt-1">
                  Wenn sich Kandidaten über FlintPlate bewerben, erscheinen sie hier.
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {applications.map((a) => (
                <Card key={a.id}>
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <button
                          className="font-semibold text-gray-900 hover:text-blue-600 hover:underline text-left"
                          onClick={() => { setProfileUserId(a.user_id); setProfileCandidateName(a.candidate_name); }}
                        >
                          {a.candidate_name ?? "Anonym"}
                        </button>
                        {a.candidate_headline && (
                          <p className="text-sm text-gray-500">{a.candidate_headline}</p>
                        )}
                        {a.candidate_location && (
                          <p className="text-xs text-gray-400">{a.candidate_location}</p>
                        )}
                        {a.applied_at && (
                          <p className="text-xs text-gray-400 mt-1">
                            Beworben: {new Date(a.applied_at).toLocaleDateString("de-DE")}
                          </p>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center gap-2 shrink-0">
                        {schedules[a.id] && (
                          <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                            schedules[a.id].status === "confirmed"
                              ? "bg-green-100 text-green-700"
                              : schedules[a.id].status === "declined"
                              ? "bg-red-100 text-red-600"
                              : "bg-yellow-100 text-yellow-700"
                          }`}>
                            📅 {new Date(schedules[a.id].scheduled_at).toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}
                            {" · "}{schedules[a.id].status === "confirmed" ? "✓" : schedules[a.id].status === "declined" ? "✗" : "ausstehend"}
                          </span>
                        )}
                        {/* Pipeline stage badge */}
                        {a.pipeline_stage_name && (
                          <span
                            className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${a.pipeline_stage_color ?? "bg-gray-100"} text-gray-700 border-gray-200`}
                          >
                            {a.pipeline_stage_name}
                          </span>
                        )}
                        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_COLORS[a.status] ?? "bg-gray-100 text-gray-500"}`}>
                          {STATUS_OPTIONS.find((o) => o.value === a.status)?.label ?? a.status}
                        </span>
                        <select
                          value={a.status}
                          disabled={updatingId === a.id}
                          onChange={(e) => handleStatusChange(a.id, e.target.value)}
                          className="rounded border border-gray-200 bg-white px-2 py-1 text-xs text-gray-700 focus:outline-none focus:ring-1 focus:ring-blue-500"
                          onClick={(e) => e.stopPropagation()}
                        >
                          {STATUS_OPTIONS.map((o) => (
                            <option key={o.value} value={o.value}>{o.label}</option>
                          ))}
                        </select>
                        {/* Pipeline stage transition */}
                        {allStages.length > 0 && (
                          <select
                            value={a.pipeline_stage_id ?? ""}
                            disabled={transitioningId === a.id}
                            onChange={(e) => { if (e.target.value) handleStageTransition(a.id, e.target.value); }}
                            className="rounded border border-blue-200 bg-blue-50 px-2 py-1 text-xs text-blue-700 focus:outline-none focus:ring-1 focus:ring-blue-500"
                            onClick={(e) => e.stopPropagation()}
                            title="Pipeline Stage wechseln"
                          >
                            <option value="">Stage wählen…</option>
                            {pipelineTemplates.map((t) => (
                              <optgroup key={t.id} label={t.name}>
                                {t.stages.map((s) => (
                                  <option key={s.id} value={s.id}>{s.name}</option>
                                ))}
                              </optgroup>
                            ))}
                          </select>
                        )}
                        {!schedules[a.id] && (
                          <button
                            onClick={() => setInterviewApp(a)}
                            className="rounded-md bg-purple-50 border border-purple-200 px-2 py-0.5 text-xs text-purple-700 hover:bg-purple-100 transition-colors"
                          >
                            📅 Interview planen
                          </button>
                        )}
                        {(a.status === "offer" || a.status === "interview") && !placements[a.id] && (
                          <button
                            onClick={() => setPlaceApp(a)}
                            className="rounded-md bg-green-50 border border-green-200 px-2 py-0.5 text-xs text-green-700 hover:bg-green-100 transition-colors"
                          >
                            ✓ Platzieren
                          </button>
                        )}
                        {placements[a.id] && (
                          <span className="rounded-full bg-green-100 border border-green-200 px-2 py-0.5 text-xs text-green-700">
                            ✓ Platziert
                          </span>
                        )}
                      </div>
                    </div>
                    {/* Vermerke inline */}
                    <div className="mt-3">
                      <VermerkPanel targetType="application" targetId={a.id} compact />
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )
        ) : (
          candidates.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <p className="text-gray-500">Keine passenden Kandidaten in der Datenbank.</p>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {candidates.map((c) => (
                <Card key={c.profile_id} className={c.passed_gate ? "border-green-200" : ""}>
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2 mb-1">
                          <h3 className="font-semibold text-gray-900">{c.full_name ?? "Anonym"}</h3>
                          <GateBadge passed={c.passed_gate} />
                        </div>
                        {c.headline && <p className="text-sm text-gray-600 mb-1">{c.headline}</p>}
                        {c.location && <p className="text-xs text-gray-400">{c.location}</p>}
                        <div className="mt-2 flex flex-wrap gap-1">
                          {c.matched_skills.map((s) => (
                            <SkillBadge key={`m-${s}`} skill={s} matched={true} />
                          ))}
                          {c.missing_skills.map((s) => (
                            <SkillBadge key={`x-${s}`} skill={s} matched={false} />
                          ))}
                        </div>
                      </div>
                      <div className="shrink-0 text-right space-y-2">
                        <div className={`inline-flex h-14 w-14 items-center justify-center rounded-full text-lg font-bold ${
                          c.score >= 75 ? "bg-green-100 text-green-700" :
                          c.score >= 50 ? "bg-yellow-100 text-yellow-700" :
                          "bg-gray-100 text-gray-500"
                        }`}>
                          {Math.round(c.score)}%
                        </div>
                        <p className="text-xs text-gray-400">Match</p>
                        <button
                          onClick={() => setScorecardCandidate(c)}
                          className="block w-full rounded-md bg-blue-50 border border-blue-200 px-2 py-0.5 text-xs text-blue-700 hover:bg-blue-100 transition-colors"
                        >
                          📄 Scorecard
                        </button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-3">
            <Button variant="outline" size="sm" disabled={page <= 1}
              onClick={() => tab === "applications" ? fetchApplications(page - 1) : fetchCandidates(page - 1)}>
              ← Zurück
            </Button>
            <span className="text-sm text-gray-500">Seite {page} / {totalPages}</span>
            <Button variant="outline" size="sm" disabled={page >= totalPages}
              onClick={() => tab === "applications" ? fetchApplications(page + 1) : fetchCandidates(page + 1)}>
              Weiter →
            </Button>
          </div>
        )}
      </main>

      {interviewApp && (
        <InterviewModal
          applicationId={interviewApp.id}
          candidateName={interviewApp.candidate_name}
          onClose={() => setInterviewApp(null)}
          onSuccess={(schedule) => {
            setSchedules((prev) => ({ ...prev, [interviewApp.id]: schedule }));
            setInterviewApp(null);
          }}
        />
      )}

      {placeApp && (
        <PlaceModal
          applicationId={placeApp.id}
          candidateName={placeApp.candidate_name}
          onClose={() => setPlaceApp(null)}
          onSuccess={(placement) => {
            setPlacements((prev) => ({ ...prev, [placeApp.id]: placement }));
            setPlaceApp(null);
          }}
        />
      )}

      {scorecardCandidate && job && (
        <ScorecardModal
          candidate={scorecardCandidate}
          recruiterName="Recruiter"
          jobTitle={job.title}
          companyName={job.company}
          onClose={() => setScorecardCandidate(null)}
        />
      )}

      {profileUserId && (
        <CandidateProfileModal
          userId={profileUserId}
          candidateName={profileCandidateName}
          onClose={() => { setProfileUserId(null); setProfileCandidateName(null); }}
        />
      )}
    </>
  );
}
