"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { authApi, recruiterApi, companyApi, zeitarbeitApi, placementApi, ApiError } from "@/lib/api";
import type {
  JobPosting, CompanyRead, WorkspaceRead,
  RecruiterDashboardStats, ZeitarbeitStats, PlacementStats,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { JobPublicationControls, jobPublicationLabel } from "@/components/recruiter/JobPublicationControls";
import { ShareJobModal } from "@/components/recruiter/ShareJobModal";
import { fetchModules, MODULE_KEYS, hasModule } from "@/lib/modules";
import {
  ClipboardList, Users, CalendarCheck, BarChart2, Columns2,
  PenTool, Workflow, Map, Building2, Handshake, Lock,
} from "lucide-react";

function formatSalary(min: number | null, max: number | null): string {
  if (!min && !max) return "";
  const fmt = (n: number) => `${Math.round(n / 1000)}k`;
  if (min && max) return `€${fmt(min)}–${fmt(max)}`;
  if (min) return `ab €${fmt(min)}`;
  return `bis €${fmt(max!)}`;
}

function KpiCard({ label, value, sub, accent }: { label: string; value: string | number; sub?: string; accent?: string }) {
  return (
    <Card>
      <CardHeader className="pb-1">
        <CardTitle className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</CardTitle>
      </CardHeader>
      <CardContent>
        <p className={`text-3xl font-bold ${accent ?? "text-gray-900"}`}>{value}</p>
        {sub && <p className="text-xs text-gray-500 mt-0.5">{sub}</p>}
      </CardContent>
    </Card>
  );
}

// moduleKey: null means always available (core nav), string means gated
const MODULE_CARDS: Array<{ href: string; icon: React.ElementType; color: string; label: string; desc: string; moduleKey: string | null }> = [
  { href: "/dashboard/applications", icon: ClipboardList, color: "text-blue-500 bg-blue-50",    label: "Bewerbungen",  desc: "Bewerbungen im eigenen Unternehmen verwalten",       moduleKey: null },
  { href: "/dashboard/candidates",   icon: Users,          color: "text-violet-500 bg-violet-50", label: "Kandidaten",   desc: "Kandidaten-Suche nach Skills, Ort & Verfügbarkeit",   moduleKey: null },
  { href: "/dashboard/interviews",   icon: CalendarCheck,  color: "text-purple-500 bg-purple-50", label: "Interviews",   desc: "Alle geplanten Interview-Termine verwalten",          moduleKey: MODULE_KEYS.INTERVIEW_SCHEDULING },
  { href: "/dashboard/analytics",    icon: BarChart2,      color: "text-amber-500 bg-amber-50",   label: "Analytics",    desc: "Bewerbungs-Trends, Funnel & Top-Inserate",            moduleKey: MODULE_KEYS.ANALYTICS_ADVANCED },
  { href: "/dashboard/kanban",       icon: Columns2,       color: "text-sky-500 bg-sky-50",       label: "Kanban",       desc: "Live-Kanban: Bewerbungen per Drag & Drop verschieben", moduleKey: MODULE_KEYS.KANBAN_PIPELINE },
  { href: "/dashboard/canvas",       icon: PenTool,        color: "text-rose-500 bg-rose-50",     label: "Canvas",       desc: "Dispositions-Board: Pool-Mitarbeiter zuweisen",       moduleKey: MODULE_KEYS.KANBAN_PIPELINE },
  { href: "/dashboard/pipeline",     icon: Workflow,       color: "text-indigo-500 bg-indigo-50", label: "Pipeline",     desc: "Bewerbungs-Stages, SLA & Freigabe-Regeln",            moduleKey: MODULE_KEYS.KANBAN_PIPELINE },
  { href: "/dashboard/map",          icon: Map,            color: "text-blue-500 bg-blue-50",label: "Karte",       desc: "Geografische Verteilung von Aufträgen & Pool",        moduleKey: MODULE_KEYS.MAP_VIEW },
  { href: "/dashboard/zeitarbeit",   icon: Building2,      color: "text-orange-500 bg-orange-50", label: "Zeitarbeit",   desc: "Aufträge verwalten, AÜG-Tracking",                   moduleKey: MODULE_KEYS.ZEITARBEIT_POOL },
  { href: "/dashboard/partner",      icon: Handshake,      color: "text-teal-500 bg-teal-50",     label: "Provisions",   desc: "Platzierungen & Provisions-Übersicht",               moduleKey: MODULE_KEYS.PARTNER_PORTAL },
];

export default function DashboardPage() {
  const router = useRouter();
  const [workspace, setWorkspace] = useState<WorkspaceRead | null>(null);
  const [jobs, setJobs] = useState<JobPosting[]>([]);
  const [total, setTotal] = useState(0);
  const [company, setCompany] = useState<CompanyRead | null>(null);
  const [kpis, setKpis] = useState<RecruiterDashboardStats | null>(null);
  const [ztStats, setZtStats] = useState<ZeitarbeitStats | null>(null);
  const [plStats, setPlStats] = useState<PlacementStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [shareJob, setShareJob] = useState<JobPosting | null>(null);
  const [modules, setModules] = useState<string[]>([]);

  const fetchData = useCallback(async () => {
    const token = auth.getAccess();
    if (!token) { router.push("/login"); return; }

    try {
      const user = await authApi.me(token);
      if (user.role !== "recruiter" && user.role !== "admin") { router.push("/profile"); return; }

      if (user.role === "admin" && !user.tenant_id) { router.replace("/admin"); return; }
      if (!user.tenant_id) { router.replace("/register/recruiter"); return; }
      const currentWorkspace = await authApi.workspace(token);
      setWorkspace(currentWorkspace);
      const isStaffing = currentWorkspace?.type === "zeitarbeit";
      const isInternal = currentWorkspace?.type === "internal_hr";
      const [jobsResp, companyResp, kpisResp, ztResp, plResp, modsResp] = await Promise.allSettled([
        recruiterApi.listJobs(token, 1, 100),
        user.company_id ? companyApi.getMine(token) : Promise.resolve(null),
        recruiterApi.getDashboardStats(token),
        isStaffing ? zeitarbeitApi.stats(token) : Promise.resolve(null),
        !isInternal ? placementApi.stats(token) : Promise.resolve(null),
        fetchModules(token),
      ]);

      if (jobsResp.status === "rejected") throw jobsResp.reason;
      setJobs(jobsResp.value.jobs); setTotal(jobsResp.value.total);
      if (companyResp.status === "fulfilled") setCompany(companyResp.value);
      if (kpisResp.status === "fulfilled") setKpis(kpisResp.value);
      if (ztResp.status === "fulfilled") setZtStats(ztResp.value);
      if (plResp.status === "fulfilled") setPlStats(plResp.value);
      if (modsResp.status === "fulfilled") setModules(modsResp.value);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) router.push("/login");
      else setError("Daten konnten nicht geladen werden.");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => { fetchData(); }, [fetchData]);

  if (loading) {
    return (
      <>

        <div className="flex min-h-[60vh] items-center justify-center">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
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

  const isStaffing = workspace?.type === "zeitarbeit";
  const isInternal = workspace?.type === "internal_hr";
  const workspaceLabel = isInternal ? "HR-Arbeitsbereich" : isStaffing ? "Disposition & Recruiting" : "Recruiting & Vermittlung";
  const visibleModules = MODULE_CARDS.filter(m => {
    if (isInternal && m.href === "/dashboard/partner") return false;
    if (!isStaffing && ["/dashboard/zeitarbeit", "/dashboard/canvas"].includes(m.href)) return false;
    return true;
  });

  const statusLabels: Record<string, string> = {
    applied: "Beworben", screening: "Screening", interview: "Interview",
    offer: "Angebot", rejected: "Abgelehnt", withdrawn: "Zurückgezogen", research: "Recherche",
  };
  const statusColors: Record<string, string> = {
    applied: "bg-blue-100 text-blue-700", screening: "bg-yellow-100 text-yellow-700",
    interview: "bg-purple-100 text-purple-700", offer: "bg-blue-100 text-blue-700",
    rejected: "bg-red-100 text-red-600", withdrawn: "bg-gray-100 text-gray-500",
    research: "bg-gray-100 text-gray-500",
  };

  return (
    <>

      <main className="mx-auto max-w-5xl px-4 py-8 space-y-8">

        {/* ── Header ─────────────────────────────────────────────────────── */}
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">{workspaceLabel}</h1>
            {company && <p className="text-sm text-gray-500 mt-0.5">{company.name}</p>}
          </div>
          <Link href="/dashboard/jobs/new">
            <Button>+ Neues Inserat</Button>
          </Link>
        </div>

        {total === 0 && (
          <section aria-label="Erste Schritte" className="rounded-2xl border border-blue-100 bg-blue-50 p-5 sm:p-6">
            <h2 className="font-semibold text-slate-900">Bereit für die erste Besetzung</h2>
            <p className="mt-1 text-sm text-slate-600">{isInternal
              ? "Veröffentliche eine Stelle, prüfe Bewerbungen und plane Gespräche gemeinsam mit deinem Team."
              : isStaffing
                ? "Lege Stellen und Einsätze an und behalte Verfügbarkeit, Arbeitszeiten und Freigaben im Blick."
                : "Erstelle dein erstes Mandat, finde passende Kandidaten und begleite sie bis zur Vermittlung."}</p>
            <div className="mt-4 flex flex-wrap gap-3">
              <Link href="/dashboard/jobs/new" className="inline-flex min-h-11 items-center rounded-lg bg-blue-600 px-4 text-sm font-semibold text-white hover:bg-blue-700">Stelle anlegen</Link>
              <Link href={isStaffing ? "/dashboard/zeitarbeit/workers" : "/dashboard/pipeline"} className="inline-flex min-h-11 items-center rounded-lg border border-blue-200 bg-white px-4 text-sm font-medium text-blue-700">{isStaffing ? "Mitarbeitende verwalten" : "Bewerbungsprozess einrichten"}</Link>
              <Link href="/dashboard/settings" className="inline-flex min-h-11 items-center px-2 text-sm text-blue-700 underline underline-offset-4">Unternehmensprofil ergänzen</Link>
            </div>
          </section>
        )}

        {/* ── KPI Row 1: Recruiting ───────────────────────────────────────── */}
        <div>
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-3">Recruiting</p>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
            <KpiCard label="Inserate" value={total} />
            <KpiCard
              label="Bewerbungen"
              value={kpis?.total_applications ?? "–"}
              sub={kpis?.new_applications_today ? `+${kpis.new_applications_today} heute` : undefined}
              accent="text-blue-600"
            />
            <KpiCard
              label="Interviews (Woche)"
              value={kpis?.interviews_this_week ?? "–"}
              accent="text-purple-600"
            />
            <KpiCard
              label="Im Interview"
              value={kpis?.applications_by_status?.["interview"] ?? 0}
            />
            <KpiCard
              label="Angebote offen"
              value={kpis?.applications_by_status?.["offer"] ?? 0}
              accent="text-blue-600"
            />
          </div>
        </div>

        {/* ── KPI Row 2: Zeitarbeit + Provisions ─────────────────────────── */}
        {!isInternal && <div>
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-3">{isStaffing ? "Einsätze & Vermittlung" : "Vermittlung"}</p>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
            {isStaffing && <><KpiCard label="Aktive Einsätze" value={ztStats?.active_assignments ?? "–"} accent="text-blue-600" />
            <KpiCard label="Pool-Mitarbeiter" value={ztStats?.workers_in_pool ?? "–"} />
            <KpiCard label="Ø Fill-Score" value={ztStats ? `${Math.round((ztStats.avg_fill_score ?? 0) * 100)}%` : "–"} /></> }
            <KpiCard
              label="Platzierungen (Monat)"
              value={plStats?.placements_this_month ?? "–"}
              accent="text-blue-600"
            />
            <KpiCard
              label="Provision (Monat)"
              value={plStats ? `€${Math.round(plStats.commission_this_month ?? 0).toLocaleString("de")}` : "–"}
              accent="text-blue-600"
            />
          </div>
        </div>}

        {/* ── Status Breakdown ────────────────────────────────────────────── */}
        {kpis && kpis.total_applications > 0 && (
          <div>
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-3">Bewerbungen nach Status</p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(kpis.applications_by_status)
                .sort((a, b) => b[1] - a[1])
                .map(([status, count]) => (
                  <span key={status} className={`rounded-full px-3 py-1 text-xs font-medium ${statusColors[status] ?? "bg-gray-100 text-gray-500"}`}>
                    {statusLabels[status] ?? status}: <strong>{count}</strong>
                  </span>
                ))}
            </div>
          </div>
        )}

        {/* ── Module Navigation ───────────────────────────────────────────── */}
        <div>
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-3">Module</p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {visibleModules.map((m) => {
              const locked = m.moduleKey !== null && !hasModule(modules, m.moduleKey);
              const Icon = m.icon;
              const card = (
                <div className={`rounded-xl border p-4 transition-all h-full ${
                  locked
                    ? "border-gray-100 bg-gray-50 opacity-60 cursor-not-allowed"
                    : "border-gray-200 bg-white hover:shadow-md hover:border-blue-200 cursor-pointer"
                }`}>
                  <div className="flex items-start justify-between mb-2.5">
                    <div className={`rounded-lg p-2 ${locked ? "bg-gray-100" : m.color.split(" ")[1]}`}>
                      <Icon size={18} className={locked ? "text-gray-500" : m.color.split(" ")[0]} />
                    </div>
                    {locked && <Lock size={13} className="text-gray-500 mt-0.5" />}
                  </div>
                  <p className="font-semibold text-sm text-gray-900">{m.label}</p>
                  <p className="text-[11px] text-gray-500 mt-0.5 leading-tight">{m.desc}</p>
                </div>
              );
              return locked ? (
                <div key={m.href} title="Modul nicht verfügbar – Admin kontaktieren">{card}</div>
              ) : (
                <Link key={m.href} href={m.href}>{card}</Link>
              );
            })}
          </div>
        </div>

        {/* ── Job list ────────────────────────────────────────────────────── */}
        <div>
          <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-3">Stellen und Entwürfe</p>
          {jobs.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <p className="text-gray-500 mb-4">Noch keine Inserate vorhanden.</p>
                <Link href="/dashboard/jobs/new"><Button>Erstes Inserat erstellen</Button></Link>
              </CardContent>
            </Card>
          ) : (
            <div className="space-y-3">
              {jobs.map((job) => (
                <Card key={job.id} className="hover:shadow-md transition-shadow">
                  <CardContent className="p-4">
                    <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2 mb-1">
                          <h2 className="font-semibold text-gray-900 truncate">{job.title}</h2>
                          {job.is_remote && (
                            <Badge className="bg-green-100 text-green-700 border-green-200 text-xs">Remote</Badge>
                          )}
                          {job.category && (
                            <Badge className="bg-blue-50 text-blue-700 border-blue-200 text-xs">{job.category}</Badge>
                          )}
                        </div>
                        <p className="text-sm text-gray-500">
                          {[job.location, formatSalary(job.salary_min, job.salary_max)].filter(Boolean).join(" · ")}
                        </p>
                        {job.required_skills.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-2">
                            {job.required_skills.slice(0, 6).map((s) => (
                              <span key={s} className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">{s}</span>
                            ))}
                            {job.required_skills.length > 6 && (
                              <span className="text-xs text-gray-500">+{job.required_skills.length - 6}</span>
                            )}
                          </div>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <Link href={`/dashboard/jobs/${job.id}`}>
                          <Button variant="outline" size="sm">Kandidaten</Button>
                        </Link>
                        {job.publication_status !== "archived" && <Link href={`/dashboard/jobs/${job.id}/edit`}>
                          <Button variant="outline" size="sm">Bearbeiten</Button>
                        </Link>}
                        <Button
                          variant="outline" size="sm"
                          className="text-[#0077b5] hover:text-[#006097] hover:border-[#0077b5]"
                          disabled={jobPublicationLabel(job) !== "Veröffentlicht"}
                          onClick={() => setShareJob(job)}
                        >
                          Teilen
                        </Button>

                      </div>
                    </div>
                    <JobPublicationControls job={job} onChange={updated => setJobs(previous => previous.map(item => item.id === updated.id ? updated : item))} />
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </main>

      {shareJob && (
        <ShareJobModal
          jobId={shareJob.id}
          jobTitle={shareJob.title}
          onClose={() => setShareJob(null)}
        />
      )}
    </>
  );
}
