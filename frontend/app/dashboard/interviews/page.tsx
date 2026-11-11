"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { recruiterApi, type RecruiterInterviewRead } from "@/lib/api";
import { Video } from "lucide-react";
import { CandidateProfileModal } from "@/components/recruiter/CandidateProfileModal";
import { InterviewEvaluationModal } from "@/components/recruiter/InterviewEvaluationModal";

const STATUS_TABS = [
  { value: "", label: "Alle" },
  { value: "proposed", label: "Vorgeschlagen" },
  { value: "confirmed", label: "Bestätigt" },
  { value: "declined", label: "Abgelehnt" },
  { value: "cancelled", label: "Abgesagt" },
];

const STATUS_COLORS: Record<string, string> = {
  proposed: "bg-yellow-100 text-yellow-700 border-yellow-200",
  confirmed: "bg-green-100 text-green-700 border-green-200",
  declined: "bg-red-100 text-red-600 border-red-200",
  cancelled: "bg-gray-100 text-gray-500 border-gray-200",
};

const STATUS_LABELS: Record<string, string> = {
  proposed: "Vorgeschlagen",
  confirmed: "Bestätigt",
  declined: "Abgelehnt",
  cancelled: "Abgesagt",
};

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("de-DE", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function googleCalendarUrl(iv: RecruiterInterviewRead): string {
  const start = new Date(iv.scheduled_at);
  const end = new Date(start.getTime() + 60 * 60 * 1000);
  const fmt = (d: Date) =>
    d.toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";
  const params = new URLSearchParams({
    action: "TEMPLATE",
    text: `Interview: ${iv.candidate_name ?? "Kandidat"} – ${iv.job_title}`,
    dates: `${fmt(start)}/${fmt(end)}`,
    details: iv.meeting_url ?? "",
  });
  return `https://calendar.google.com/calendar/render?${params}`;
}

function downloadIcs(iv: RecruiterInterviewRead) {
  const start = new Date(iv.scheduled_at);
  const end = new Date(start.getTime() + 60 * 60 * 1000);
  const fmt = (d: Date) => d.toISOString().replace(/[-:]/g, "").split(".")[0] + "Z";
  const uid = `interview-${iv.id}@FlintPlate`;
  const ics = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//FlintPlate//FlintPlate//DE",
    "BEGIN:VEVENT",
    `UID:${uid}`,
    `DTSTART:${fmt(start)}`,
    `DTEND:${fmt(end)}`,
    `SUMMARY:Interview: ${iv.candidate_name ?? "Kandidat"} – ${iv.job_title}`,
    iv.meeting_url ? `URL:${iv.meeting_url}` : "",
    iv.notes ? `DESCRIPTION:${iv.notes.replace(/\n/g, "\\n")}` : "",
    "END:VEVENT",
    "END:VCALENDAR",
  ]
    .filter(Boolean)
    .join("\r\n");

  const blob = new Blob([ics], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `interview-${iv.candidate_name ?? iv.id}.ics`;
  a.click();
  URL.revokeObjectURL(url);
}

export default function RecruiterInterviewsPage() {
  const router = useRouter();
  const [interviews, setInterviews] = useState<RecruiterInterviewRead[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const [upcomingOnly, setUpcomingOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [cancellingId, setCancellingId] = useState<string | null>(null);
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [evaluationIv, setEvaluationIv] = useState<RecruiterInterviewRead | null>(null);

  const PAGE_SIZE = 50;

  const load = useCallback(
    (p = 1) => {
      const token = auth.getAccess();
      if (!token) { router.push("/login"); return; }
      setLoading(true);
      setError(null);
      recruiterApi
        .listInterviews(token, {
          interview_status: statusFilter || undefined,
          upcoming_only: upcomingOnly || undefined,
          page: p,
          page_size: PAGE_SIZE,
        })
        .then((res) => {
          setInterviews(res.interviews);
          setTotal(res.total);
          setPage(p);
        })
        .catch(() => setError("Fehler beim Laden der Interviews."))
        .finally(() => setLoading(false));
    },
    [statusFilter, upcomingOnly, router],
  );

  useEffect(() => { load(1); }, [load]);

  async function handleCancel(iv: RecruiterInterviewRead) {
    if (!confirm(`Interview mit ${iv.candidate_name ?? "Kandidat"} wirklich absagen?`)) return;
    const token = auth.getAccess();
    if (!token) return;
    setCancellingId(iv.id);
    try {
      await recruiterApi.cancelInterview(token, iv.application_id);
      setInterviews((prev) =>
        prev.map((x) => (x.id === iv.id ? { ...x, status: "cancelled" } : x)),
      );
    } catch {
      alert("Absagen fehlgeschlagen.");
    } finally {
      setCancellingId(null);
    }
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);
  const now = new Date();

  return (
    <div className="min-h-screen bg-gray-50">

      <main className="mx-auto max-w-5xl px-4 py-8 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Interviews</h1>
            <p className="mt-1 text-sm text-gray-500">Alle geplanten Interview-Termine</p>
          </div>
          <span className="text-sm text-gray-500">{total} Termine</span>
        </div>

        {/* Filters */}
        <div className="flex flex-wrap items-center gap-3">
          {/* Status tabs */}
          <div className="flex rounded-lg border border-gray-200 overflow-hidden bg-white">
            {STATUS_TABS.map((tab) => (
              <button
                key={tab.value}
                onClick={() => { setStatusFilter(tab.value); setPage(1); }}
                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                  statusFilter === tab.value
                    ? "bg-blue-600 text-white"
                    : "text-gray-600 hover:bg-gray-50"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Upcoming toggle */}
          <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
            <input
              type="checkbox"
              checked={upcomingOnly}
              onChange={(e) => { setUpcomingOnly(e.target.checked); setPage(1); }}
              className="rounded"
            />
            Nur bevorstehende
          </label>
        </div>

        {/* Table */}
        <div className="rounded-2xl border border-gray-200 bg-white shadow-sm overflow-hidden">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
            </div>
          ) : error ? (
            <div className="py-16 text-center text-sm text-red-500">{error}</div>
          ) : interviews.length === 0 ? (
            <div className="py-16 text-center text-sm text-gray-400">
              Keine Interview-Termine gefunden.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b border-gray-200 bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Kandidat</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Stelle</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Termin</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Status</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Aktionen</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {interviews.map((iv) => {
                  const isPast = new Date(iv.scheduled_at) < now;
                  return (
                    <tr
                      key={iv.id}
                      className={`transition-colors ${isPast ? "opacity-60" : "hover:bg-gray-50"}`}
                    >
                      {/* Candidate */}
                      <td className="px-4 py-3">
                        <button
                          onClick={() => { setSelectedUserId(iv.candidate_user_id); setSelectedName(iv.candidate_name); }}
                          className="font-medium text-gray-900 hover:text-blue-600 text-left"
                        >
                          {iv.candidate_name ?? "—"}
                        </button>
                        <p className="text-xs text-gray-400">{iv.candidate_email}</p>
                      </td>

                      {/* Job */}
                      <td className="px-4 py-3">
                        <Link
                          href={`/dashboard/jobs/${iv.job_id}`}
                          className="text-gray-700 hover:text-blue-600 truncate block max-w-[180px]"
                        >
                          {iv.job_title}
                        </Link>
                      </td>

                      {/* Date/time */}
                      <td className="px-4 py-3 text-gray-700 whitespace-nowrap">
                        {formatDateTime(iv.scheduled_at)}
                        {isPast && <span className="ml-1 text-xs text-gray-400">(vergangen)</span>}
                      </td>

                      {/* Status */}
                      <td className="px-4 py-3">
                        <span
                          className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${
                            STATUS_COLORS[iv.status] ?? "bg-gray-100 text-gray-500"
                          }`}
                        >
                          {STATUS_LABELS[iv.status] ?? iv.status}
                        </span>
                      </td>

                      {/* Actions */}
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1.5 flex-wrap">
                          {iv.status === "confirmed" && !isPast && (
                            <button
                              onClick={() => router.push(`/dashboard/interviews/room/${iv.id}`)}
                              className="flex items-center gap-1 rounded border border-blue-200 bg-blue-50 px-2 py-0.5 text-xs text-blue-700 hover:bg-blue-100 font-medium whitespace-nowrap"
                            >
                              <Video size={11} />
                              Beitreten
                            </button>
                          )}
                          {iv.meeting_url && (
                            <a
                              href={iv.meeting_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="rounded border border-blue-200 bg-blue-50 px-2 py-0.5 text-xs text-blue-700 hover:bg-blue-100 whitespace-nowrap"
                            >
                              Meeting
                            </a>
                          )}
                          {iv.status === "confirmed" && (
                            <>
                              <a
                                href={googleCalendarUrl(iv)}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="rounded border border-gray-200 px-2 py-0.5 text-xs text-gray-600 hover:border-gray-400 whitespace-nowrap"
                              >
                                Google Cal
                              </a>
                              <button
                                onClick={() => downloadIcs(iv)}
                                className="rounded border border-gray-200 px-2 py-0.5 text-xs text-gray-600 hover:border-gray-400 whitespace-nowrap"
                              >
                                .ics
                              </button>
                            </>
                          )}
                          {(iv.status === "confirmed" || iv.status === "declined" || iv.status === "cancelled" || isPast) && (
                            <button
                              onClick={(e) => { e.stopPropagation(); setEvaluationIv(iv); }}
                              className="rounded border border-purple-200 bg-purple-50 px-2 py-0.5 text-xs text-purple-700 hover:bg-purple-100 whitespace-nowrap"
                            >
                              Bewerten
                            </button>
                          )}
                          {(iv.status === "proposed" || iv.status === "confirmed") && (
                            <button
                              onClick={() => handleCancel(iv)}
                              disabled={cancellingId === iv.id}
                              className="rounded border border-red-200 bg-red-50 px-2 py-0.5 text-xs text-red-600 hover:bg-red-100 disabled:opacity-50 whitespace-nowrap"
                            >
                              {cancellingId === iv.id ? "…" : "Absagen"}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-2">
            <button
              onClick={() => load(page - 1)}
              disabled={page === 1 || loading}
              className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:border-gray-300 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              ← Zurück
            </button>
            <span className="text-sm text-gray-500">Seite {page} von {totalPages}</span>
            <button
              onClick={() => load(page + 1)}
              disabled={page === totalPages || loading}
              className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:border-gray-300 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Weiter →
            </button>
          </div>
        )}
      </main>

      {selectedUserId && (
        <CandidateProfileModal
          userId={selectedUserId}
          candidateName={selectedName}
          onClose={() => { setSelectedUserId(null); setSelectedName(null); }}
        />
      )}

      {evaluationIv && (
        <InterviewEvaluationModal
          applicationId={evaluationIv.application_id}
          candidateName={evaluationIv.candidate_name}
          jobTitle={evaluationIv.job_title}
          onClose={() => setEvaluationIv(null)}
        />
      )}
    </div>
  );
}
