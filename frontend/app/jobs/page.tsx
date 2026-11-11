"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";
import {
  jobsApi,
  jobApplicationApi,
  savedJobsApi,
  applicationsApi,
  ApiError,
} from "@/lib/api";
import type { JobFeedResponse, JobMatchResult, JobPosting } from "@/lib/api";
import { Navbar } from "@/components/layout/Navbar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { CoverLetterModal } from "@/components/ai/CoverLetterModal";
import { normalizeSkills } from "@/lib/skills";

// ── Job detail drawer ──────────────────────────────────────────────────────

function JobDetailDrawer({
  result,
  applied,
  applying,
  saved,
  onClose,
  onApply,
  onDirectApply,
  onToggleSave,
}: {
  result: JobMatchResult;
  applied: boolean;
  applying: boolean;
  saved: boolean;
  onClose: () => void;
  onApply: (job: JobPosting) => void;
  onDirectApply: (job: JobPosting) => void;
  onToggleSave: (job: JobPosting) => void;
}) {
  const { job, score, explanation } = result;
  const salary = formatSalary(job.salary_min, job.salary_max);

  return (
    <div className="fixed inset-0 z-50 flex" onClick={onClose}>
      <div
        className="ml-auto h-full w-full max-w-lg bg-white shadow-2xl overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 bg-white border-b border-gray-100 px-5 py-4 flex items-start justify-between gap-3 z-10">
          <div className="min-w-0">
            <h2 className="font-bold text-gray-900 text-lg leading-snug truncate">{job.title}</h2>
            <p className="text-sm text-gray-500 mt-0.5">
              {job.company}
              {job.location && <span> · {job.location}</span>}
            </p>
          </div>
          <button onClick={onClose} className="shrink-0 text-gray-400 hover:text-gray-600 text-lg mt-0.5">✕</button>
        </div>

        <div className="p-5 space-y-5">
          {/* Meta pills */}
          <div className="flex flex-wrap gap-2">
            {job.is_remote && <Badge className="bg-green-100 text-green-700 border-green-200">Remote</Badge>}
            {job.employment_type && <Badge variant="secondary">{job.employment_type}</Badge>}
            {job.category && <Badge variant="secondary">{job.category}</Badge>}
            {salary && <Badge className="bg-blue-50 text-blue-700 border-blue-200">{salary}</Badge>}
            <Badge className={
              score >= 75 ? "bg-green-100 text-green-700 border-green-200" :
              score >= 50 ? "bg-yellow-100 text-yellow-700 border-yellow-200" :
              "bg-gray-100 text-gray-600 border-gray-200"
            }>
              {explanation?.matching_mode === "skills_only" && !job.required_skills.length ? "Anforderungen offen" : `${Math.round(score)}% Match`}
            </Badge>
          </div>

          {/* Apply buttons */}
          <div className="flex gap-2 flex-wrap">
            <button
              onClick={() => { if (!applied && !applying) onDirectApply(job); }}
              disabled={applied || applying}
              className={`flex-1 rounded-lg px-4 py-2 text-sm font-semibold transition-colors ${
                applied ? "bg-green-100 text-green-700 cursor-default" :
                applying ? "bg-gray-100 text-gray-400 cursor-wait" :
                "bg-blue-600 text-white hover:bg-blue-700"
              }`}
            >
              {applied ? "✓ Beworben" : applying ? "…" : "Jetzt bewerben"}
            </button>
            <button
              onClick={() => onApply(job)}
              className="rounded-lg border border-purple-200 bg-purple-50 px-3 py-2 text-sm text-purple-700 hover:bg-purple-100 transition-colors"
            >
              ✨ Anschreiben
            </button>
            <button
              onClick={() => onToggleSave(job)}
              className={`rounded-lg border px-3 py-2 text-sm transition-colors ${
                saved
                  ? "border-amber-300 bg-amber-50 text-amber-700 hover:bg-amber-100"
                  : "border-gray-200 text-gray-500 hover:bg-gray-50"
              }`}
              title={saved ? "Aus Merkliste entfernen" : "Merken"}
            >
              {saved ? "★ Gemerkt" : "☆ Merken"}
            </button>
            {job.url && (
              <a
                href={job.url}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
              >
                Extern →
              </a>
            )}
          </div>

          {/* Skills match */}
          {explanation && (explanation.matched_skills.length > 0 || explanation.missing_skills.length > 0) && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">Skills-Match</p>
              <div className="flex flex-wrap gap-1.5">
                {normalizeSkills(explanation.matched_skills).map((s) => (
                  <span key={s} className="rounded-full bg-green-50 border border-green-200 px-2.5 py-0.5 text-xs text-green-700">✓ {s}</span>
                ))}
                {normalizeSkills(explanation.missing_skills).map((s) => (
                  <span key={s} className="rounded-full bg-red-50 border border-red-200 px-2.5 py-0.5 text-xs text-red-600">– {s}</span>
                ))}
              </div>
            </div>
          )}

          {/* Required skills */}
          {job.required_skills.length > 0 && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">Geforderte Skills</p>
              <div className="flex flex-wrap gap-1.5">
                {normalizeSkills(job.required_skills).map((s) => (
                  <span key={s} className="rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-700">{s}</span>
                ))}
              </div>
            </div>
          )}

          {/* Description */}
          {job.description && (
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">Stellenbeschreibung</p>
              <div className="text-sm text-gray-700 leading-relaxed whitespace-pre-line">
                {job.description}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Score badge ────────────────────────────────────────────────────────────

function ScoreBadge({ score }: { score: number }) {
  const color =
    score >= 75 ? "bg-green-100 text-green-800 border-green-200" :
    score >= 50 ? "bg-yellow-100 text-yellow-800 border-yellow-200" :
                  "bg-gray-100 text-gray-600 border-gray-200";
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold ${color}`}>
      {Math.round(score)}% Match
    </span>
  );
}

// ── Salary formatter ──────────────────────────────────────────────────────

function formatSalary(min: number | null, max: number | null): string {
  if (!min && !max) return "";
  const fmt = (n: number) => `${Math.round(n / 1000)}k`;
  if (min && max) return `€${fmt(min)}–${fmt(max)}`;
  if (min) return `ab €${fmt(min)}`;
  return `bis €${fmt(max!)}`;
}

// ── Job card ──────────────────────────────────────────────────────────────

function JobCard({
  result,
  onExpand,
  onApply,
  onDirectApply,
  onToggleSave,
  applied,
  applying,
  saved,
}: {
  result: JobMatchResult;
  onExpand: () => void;
  onApply: (job: JobPosting) => void;
  onDirectApply: (job: JobPosting) => void;
  onToggleSave: (job: JobPosting) => void;
  applied: boolean;
  applying: boolean;
  saved: boolean;
}) {
  const { job, score, explanation } = result;
  return (
    <Card className="hover:shadow-md transition-shadow cursor-pointer" onClick={onExpand}>
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-semibold text-gray-900 truncate">{job.title}</h3>
              {job.is_remote && (
                <Badge variant="secondary" className="text-xs shrink-0">Remote</Badge>
              )}
            </div>
            <p className="text-sm text-gray-500 mt-0.5">
              {job.company}
              {job.location && <span> · {job.location}</span>}
              {formatSalary(job.salary_min, job.salary_max) && (
                <span className="text-blue-600 font-medium"> · {formatSalary(job.salary_min, job.salary_max)}</span>
              )}
            </p>

            {explanation && (
              <div className="mt-2 flex flex-wrap gap-1">
                {normalizeSkills(explanation.matched_skills).slice(0, 5).map((s) => (
                  <span key={s} className="rounded bg-green-50 px-1.5 py-0.5 text-xs text-green-700 border border-green-200">
                    ✓ {s}
                  </span>
                ))}
                {normalizeSkills(explanation.missing_skills).slice(0, 3).map((s) => (
                  <span key={s} className="rounded bg-red-50 px-1.5 py-0.5 text-xs text-red-600 border border-red-200">
                    – {s}
                  </span>
                ))}
              </div>
            )}
          </div>
          <div className="shrink-0 text-right space-y-1.5">
            {explanation?.matching_mode === "skills_only" && !job.required_skills.length
              ? <span className="text-xs text-gray-500">Anforderungen offen</span>
              : <ScoreBadge score={score} />}
            <div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  if (!applied && !applying) onDirectApply(job);
                }}
                disabled={applied || applying}
                className={`block w-full rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                  applied
                    ? "bg-green-100 text-green-700 cursor-default"
                    : applying
                    ? "bg-gray-100 text-gray-400 cursor-wait"
                    : "bg-blue-600 text-white hover:bg-blue-700"
                }`}
              >
                {applied ? "✓ Beworben" : applying ? "…" : "Jetzt bewerben"}
              </button>
            </div>
            {job.url && (
              <div>
                <a
                  href={job.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="text-xs text-blue-600 hover:underline"
                >
                  Zur Stelle →
                </a>
              </div>
            )}
            <div>
              <button
                onClick={(e) => { e.stopPropagation(); onApply(job); }}
                className="text-xs text-purple-600 hover:text-purple-800 hover:underline"
              >
                ✨ Anschreiben
              </button>
            </div>
            <div>
              <button
                onClick={(e) => { e.stopPropagation(); onToggleSave(job); }}
                className={`text-xs transition-colors ${saved ? "text-amber-600 hover:text-amber-800" : "text-gray-400 hover:text-gray-600"}`}
              >
                {saved ? "★ Gemerkt" : "☆ Merken"}
              </button>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Filters ───────────────────────────────────────────────────────────────

interface Filters {
  remoteOnly: boolean;
  minSalary: string;
  location: string;
  category: string;
  search: string;
}

const CATEGORIES = [
  "IT/Software",
  "Data & Analytics",
  "Design/UX",
  "Marketing",
  "Sales/Vertrieb",
  "Finance",
  "HR/People",
  "Operations",
  "Management",
  "Customer Success",
  "Engineering",
  "Sonstige",
];

function FilterBar({ filters, onChange }: {
  filters: Filters;
  onChange: (f: Filters) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border border-gray-200 bg-white p-3">
      <Input
        placeholder="Stichwort, Skill, Titel…"
        value={filters.search}
        onChange={(e) => onChange({ ...filters, search: e.target.value })}
        className="h-8 w-52 text-sm"
      />

      <select
        value={filters.category}
        onChange={(e) => onChange({ ...filters, category: e.target.value })}
        className="h-8 rounded-md border border-input bg-transparent px-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <option value="">Alle Kategorien</option>
        {CATEGORIES.map((c) => (
          <option key={c} value={c}>{c}</option>
        ))}
      </select>

      <div className="flex items-center gap-2">
        <input
          id="remote"
          type="checkbox"
          checked={filters.remoteOnly}
          onChange={(e) => onChange({ ...filters, remoteOnly: e.target.checked })}
          className="rounded"
        />
        <label htmlFor="remote" className="text-sm text-gray-700 cursor-pointer">Nur Remote</label>
      </div>

      <Input
        type="number"
        placeholder="Min. Gehalt €"
        value={filters.minSalary}
        onChange={(e) => onChange({ ...filters, minSalary: e.target.value })}
        className="h-8 w-36 text-sm"
      />

      <Input
        placeholder="Standort"
        value={filters.location}
        onChange={(e) => onChange({ ...filters, location: e.target.value })}
        className="h-8 w-36 text-sm"
      />
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────

export default function JobsPage() {
  const router = useRouter();
  const [feed, setFeed] = useState<JobFeedResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<Filters>({
    remoteOnly: false,
    minSalary: "",
    location: "",
    category: "",
    search: "",
  });
  const [page, setPage] = useState(1);
  const [applyJob, setApplyJob] = useState<JobPosting | null>(null);
  const [selectedResult, setSelectedResult] = useState<JobMatchResult | null>(null);
  const [appliedIds, setAppliedIds] = useState<Set<string>>(new Set());
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const [savedIds, setSavedIds] = useState<Set<string>>(new Set());
  const [applyMessage, setApplyMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  const fetchJobs = useCallback(async (f: Filters, p: number) => {
    const token = auth.getAccess();
    if (!token) { router.replace("/login"); return; }
    setLoading(true);
    setError(null);
    try {
      const data = await jobsApi.recommended(token, {
        remote_only: f.remoteOnly,
        min_salary: f.minSalary ? Number(f.minSalary) : undefined,
        location: f.location || undefined,
        category: f.category || undefined,
        text_search: f.search || undefined,
        page: p,
        page_size: 20,
      });
      setFeed(data);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Fehler beim Laden der Jobs.");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // run once on mount only

  useEffect(() => {
    fetchJobs(filters, page);
  }, [filters, page, fetchJobs]);

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) return;
    savedJobsApi.listIds(token).then((ids) => setSavedIds(new Set(ids))).catch(() => {});
    applicationsApi
      .list(token)
      .then((applications) => {
        setAppliedIds(
          new Set(
            applications
              .filter((application) => application.job_id !== null)
              .map((application) => application.job_id as string),
          ),
        );
      })
      .catch(() => {});
  }, []);

  async function handleDirectApply(job: JobPosting) {
    const token = auth.getAccess();
    if (!token) { router.replace("/login"); return; }
    setApplyingId(job.id);
    setApplyMessage(null);
    try {
      const response = await jobApplicationApi.apply(token, job.id);
      setAppliedIds((prev) => new Set([...prev, job.id]));
      setApplyMessage({ type: "success", text: response.message || "Bewerbung erfolgreich gesendet." });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        setAppliedIds((prev) => new Set([...prev, job.id]));
        setApplyMessage({ type: "error", text: "Du hast dich bereits auf diesen Job beworben." });
      } else {
        setApplyMessage({
          type: "error",
          text: err instanceof ApiError ? err.detail : "Bewerbung fehlgeschlagen.",
        });
      }
    } finally {
      setApplyingId(null);
    }
  }

  async function handleToggleSave(job: JobPosting) {
    const token = auth.getAccess();
    if (!token) return;
    const isSaved = savedIds.has(job.id);
    // Optimistic update
    setSavedIds((prev) => {
      const next = new Set(prev);
      if (isSaved) next.delete(job.id); else next.add(job.id);
      return next;
    });
    try {
      if (isSaved) {
        await savedJobsApi.unsave(token, job.id);
      } else {
        await savedJobsApi.save(token, job.id);
      }
    } catch {
      // Revert on error
      setSavedIds((prev) => {
        const next = new Set(prev);
        if (isSaved) next.add(job.id); else next.delete(job.id);
        return next;
      });
    }
  }

  const totalPages = feed ? Math.ceil(feed.total / 20) : 1;

  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-3xl px-4 py-8">
        {applyMessage && (
          <div
            role="status"
            aria-live="polite"
            className={`mb-4 rounded-lg border px-4 py-3 text-sm ${
              applyMessage.type === "success"
                ? "border-green-200 bg-green-50 text-green-800"
                : "border-amber-200 bg-amber-50 text-amber-800"
            }`}
          >
            {applyMessage.type === "success" ? "✓ " : "⚠ "}{applyMessage.text}
          </div>
        )}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Empfohlene Stellen</h1>
            {feed && (
              <p className="text-sm text-gray-400 mt-0.5">{feed.total} Jobs gefunden</p>
            )}
          </div>
        </div>

        <FilterBar filters={filters} onChange={(f) => { setFilters(f); setPage(1); }} />

        <Separator className="my-4" />

        {feed?.jobs.some(result => result.explanation?.matching_mode === "skills_only") && (
          <p className="mb-4 text-sm text-gray-600">Der Vergleich verwendet aktuell die angegebenen Fähigkeiten. Die semantische Suche ist noch nicht verfügbar. Ohne angegebene Anforderungen wird kein Prozentwert angezeigt.</p>
        )}

        {error && (
          <p className="text-sm text-red-600 mb-4">{error}</p>
        )}

        {loading ? (
          <div className="flex justify-center py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
          </div>
        ) : feed?.jobs.length === 0 ? (
          <div className="text-center py-16 text-gray-400">
            <p className="text-lg mb-2">Keine Jobs gefunden</p>
            <p className="text-sm">Klicke auf &quot;Testjobs laden&quot; um Demo-Daten einzuspielen.</p>
          </div>
        ) : (
          <div className="space-y-3">
            {feed?.jobs.map((result) => (
              <JobCard
                key={result.job.id}
                result={result}
                onExpand={() => setSelectedResult(result)}
                onApply={setApplyJob}
                onDirectApply={handleDirectApply}
                onToggleSave={handleToggleSave}
                applied={appliedIds.has(result.job.id)}
                applying={applyingId === result.job.id}
                saved={savedIds.has(result.job.id)}
              />
            ))}
          </div>
        )}

      {applyJob && (
        <CoverLetterModal
          initialCompany={applyJob.company}
          initialPosition={applyJob.title}
          jobId={applyJob.id}
          jobDescription={applyJob.description}
          onClose={() => setApplyJob(null)}
        />
      )}

      {selectedResult && (
        <JobDetailDrawer
          result={selectedResult}
          applied={appliedIds.has(selectedResult.job.id)}
          applying={applyingId === selectedResult.job.id}
          saved={savedIds.has(selectedResult.job.id)}
          onClose={() => setSelectedResult(null)}
          onApply={(job) => { setSelectedResult(null); setApplyJob(job); }}
          onDirectApply={(job) => { handleDirectApply(job); }}
          onToggleSave={handleToggleSave}
        />
      )}

        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-3 mt-6">
            <Button
              variant="outline"
              size="sm"
              disabled={page <= 1}
              onClick={() => setPage(page - 1)}
            >
              ← Zurück
            </Button>
            <span className="text-sm text-gray-500">{page} / {totalPages}</span>
            <Button
              variant="outline"
              size="sm"
              disabled={page >= totalPages}
              onClick={() => setPage(page + 1)}
            >
              Weiter →
            </Button>
          </div>
        )}
      </main>
    </>
  );
}
