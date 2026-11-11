"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { auth } from "@/lib/auth";
import Link from "next/link";
import { recruiterApi, type RecruiterAllApplication } from "@/lib/api";
import { CandidateProfileModal } from "@/components/recruiter/CandidateProfileModal";
import { InterviewModal } from "@/components/recruiter/InterviewModal";
import { InterviewEvaluationModal } from "@/components/recruiter/InterviewEvaluationModal";

const STATUS_OPTIONS = [
  { value: "", label: "Alle Status" },
  { value: "research", label: "Recherche" },
  { value: "applied", label: "Beworben" },
  { value: "screening", label: "Screening" },
  { value: "interview", label: "Interview" },
  { value: "offer", label: "Angebot" },
  { value: "rejected", label: "Abgelehnt" },
  { value: "withdrawn", label: "Zurückgezogen" },
];

const STATUS_COLORS: Record<string, string> = {
  research: "bg-gray-100 text-gray-600",
  applied: "bg-blue-100 text-blue-700",
  screening: "bg-purple-100 text-purple-700",
  interview: "bg-yellow-100 text-yellow-700",
  offer: "bg-green-100 text-green-700",
  rejected: "bg-red-100 text-red-600",
  withdrawn: "bg-orange-100 text-orange-600",
};

const STATUS_LABELS: Record<string, string> = {
  research: "Recherche",
  applied: "Beworben",
  screening: "Screening",
  interview: "Interview",
  offer: "Angebot",
  rejected: "Abgelehnt",
  withdrawn: "Zurückgezogen",
};

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
}

export default function RecruiterApplicationsPage() {
  return <Suspense fallback={<p role="status" className="p-8">Bewerbungen werden geladen …</p>}><ApplicationsWorkspace /></Suspense>;
}

function ApplicationsWorkspace() {
  const applicationId = useSearchParams().get("application");
  const router = useRouter();
  const [apps, setApps] = useState<RecruiterAllApplication[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [interviewApp, setInterviewApp] = useState<RecruiterAllApplication | null>(null);
  const [evaluationApp, setEvaluationApp] = useState<RecruiterAllApplication | null>(null);
  const [updatingId, setUpdatingId] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [editingNoteId, setEditingNoteId] = useState<string | null>(null);
  const [noteValue, setNoteValue] = useState("");

  // Bulk selection
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [bulkStatus, setBulkStatus] = useState("rejected");
  const [bulkUpdating, setBulkUpdating] = useState(false);

  const PAGE_SIZE = 50;

  async function handleNoteSave(app: RecruiterAllApplication) {
    if (!app.job_id) return;
    const token = auth.getAccess();
    if (!token) return;
    const prevNote = app.notes;
    const newNote = noteValue;
    setApps((list) => list.map((a) => a.id === app.id ? { ...a, notes: newNote } : a));
    setEditingNoteId(null);
    try {
      await recruiterApi.updateApplicationStatus(token, app.job_id, app.id, app.status, newNote);
    } catch {
      setApps((list) => list.map((a) => a.id === app.id ? { ...a, notes: prevNote } : a));
    }
  }

  async function handleStatusChange(app: RecruiterAllApplication, newStatus: string) {
    if (!app.job_id || newStatus === app.status) return;
    const token = auth.getAccess();
    if (!token) return;
    const prev = app.status;
    setApps((list) => list.map((a) => a.id === app.id ? { ...a, status: newStatus } : a));
    setUpdatingId(app.id);
    try {
      await recruiterApi.updateApplicationStatus(token, app.job_id, app.id, newStatus);
    } catch {
      setApps((list) => list.map((a) => a.id === app.id ? { ...a, status: prev } : a));
    } finally {
      setUpdatingId(null);
    }
  }

  async function handleBulkUpdate() {
    if (selected.size === 0) return;
    const token = auth.getAccess();
    if (!token) return;
    setBulkUpdating(true);
    try {
      await recruiterApi.bulkUpdateApplications(token, Array.from(selected), bulkStatus);
      setApps((list) =>
        list.map((a) => selected.has(a.id) ? { ...a, status: bulkStatus } : a),
      );
      setSelected(new Set());
    } catch {
      alert("Massenaktualisierung fehlgeschlagen.");
    } finally {
      setBulkUpdating(false);
    }
  }

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) { router.push("/login"); return; }

    setLoading(true);
    setError(null);
    setSelected(new Set());
    recruiterApi
      .getAllApplications(token, {
        status: statusFilter || undefined,
        page,
        page_size: PAGE_SIZE,
        application_id: applicationId ?? undefined,
      })
      .then((res) => {
        setApps(res.applications);
        setTotal(res.total);
      })
      .catch(() => setError("Fehler beim Laden der Bewerbungen."))
      .finally(() => setLoading(false));
  }, [statusFilter, page, router, applicationId]);

  const q = searchQuery.toLowerCase().trim();
  const visibleApps = q
    ? apps.filter(
        (a) =>
          (a.candidate_name ?? "").toLowerCase().includes(q) ||
          (a.job_title ?? "").toLowerCase().includes(q) ||
          (a.candidate_headline ?? "").toLowerCase().includes(q),
      )
    : apps;

  const allVisibleSelected =
    visibleApps.length > 0 && visibleApps.every((a) => selected.has(a.id));

  function toggleSelectAll() {
    if (allVisibleSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(visibleApps.map((a) => a.id)));
    }
  }

  function toggleOne(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="min-h-screen bg-gray-50">

      <main className="mx-auto max-w-5xl px-4 py-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Alle Bewerbungen</h1>
          <p className="mt-1 text-sm text-gray-500">
            Übersicht aller Bewerbungen auf Ihre Stelleninserate
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500">
            {total} {total === 1 ? "Bewerbung" : "Bewerbungen"}
          </span>
          <button
            onClick={async () => {
              const token = auth.getAccess();
              if (!token) return;
              setExporting(true);
              try { await recruiterApi.exportApplicationsCsv(token, statusFilter || undefined); }
              catch { /* ignore */ }
              finally { setExporting(false); }
            }}
            disabled={exporting || total === 0}
            className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs text-gray-600 hover:border-gray-300 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            {exporting ? "…" : "↓ CSV Export"}
          </button>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-3 flex-wrap">
        <input
          type="text"
          placeholder="Name oder Stelle suchen…"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[220px]"
        />
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
          className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>
      </div>

      {/* Bulk actions bar */}
      {selected.size > 0 && (
        <div className="flex items-center gap-3 rounded-xl border border-blue-200 bg-blue-50 px-4 py-2.5">
          <span className="text-sm font-medium text-blue-700">
            {selected.size} ausgewählt
          </span>
          <select
            value={bulkStatus}
            onChange={(e) => setBulkStatus(e.target.value)}
            className="rounded border border-blue-200 bg-white px-2 py-1 text-sm text-gray-700 focus:outline-none focus:ring-1 focus:ring-blue-400"
          >
            {STATUS_OPTIONS.filter((o) => o.value).map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <button
            onClick={handleBulkUpdate}
            disabled={bulkUpdating}
            className="rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {bulkUpdating ? "Aktualisiere…" : "Status setzen"}
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="ml-auto text-xs text-blue-500 hover:text-blue-700"
          >
            Auswahl aufheben
          </button>
        </div>
      )}

      {/* Table */}
      <div className="rounded-2xl border border-gray-200 bg-white shadow-sm overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
          </div>
        ) : error ? (
          <div className="py-16 text-center text-sm text-red-500">{error}</div>
        ) : visibleApps.length === 0 ? (
          <div className="py-16 text-center text-sm text-gray-400">
            {apps.length === 0
              ? (statusFilter ? "Keine Bewerbungen mit diesem Status." : "Noch keine Bewerbungen eingegangen.")
              : "Keine Treffer für Ihre Suche."}
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead className="border-b border-gray-200 bg-gray-50">
              <tr>
                <th className="pl-4 pr-2 py-3 text-left">
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    onChange={toggleSelectAll}
                    className="rounded"
                  />
                </th>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Kandidat</th>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Stelle</th>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Status</th>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Datum</th>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Notizen</th>
                <th className="px-4 py-3 text-left font-medium text-gray-500">Aktionen</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {visibleApps.map((app) => (
                <tr
                  key={app.id}
                  className={`transition-colors cursor-pointer ${
                    selected.has(app.id) ? "bg-blue-50" : "hover:bg-gray-50"
                  }`}
                  onClick={() => { setSelectedUserId(app.user_id); setSelectedName(app.candidate_name); }}
                >
                  <td className="pl-4 pr-2 py-3" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selected.has(app.id)}
                      onChange={() => toggleOne(app.id)}
                      className="rounded"
                    />
                  </td>
                  <td className="px-4 py-3">
                    <p className="font-medium text-gray-900 hover:text-blue-600">
                      {app.candidate_name ?? <span className="text-gray-400">Anonym</span>}
                    </p>
                    {app.candidate_headline && (
                      <p className="text-xs text-gray-500 truncate max-w-[200px]">{app.candidate_headline}</p>
                    )}
                    {app.candidate_location && (
                      <p className="text-xs text-gray-400">{app.candidate_location}</p>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <p className="text-gray-900 font-medium truncate max-w-[200px]">
                      {app.job_title ?? "—"}
                    </p>
                  </td>
                  <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                    <select
                      value={app.status}
                      disabled={updatingId === app.id || !app.job_id}
                      onChange={(e) => handleStatusChange(app, e.target.value)}
                      className={`rounded-full px-2.5 py-0.5 text-xs font-medium border-0 cursor-pointer focus:outline-none focus:ring-2 focus:ring-blue-400 disabled:opacity-50 ${
                        STATUS_COLORS[app.status] ?? "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {STATUS_OPTIONS.filter((o) => o.value).map((o) => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                      ))}
                    </select>
                  </td>
                  <td className="px-4 py-3 text-gray-500">
                    {formatDate(app.applied_at ?? app.created_at)}
                  </td>
                  <td className="px-4 py-3 max-w-[220px]" onClick={(e) => e.stopPropagation()}>

                    {editingNoteId === app.id ? (
                      <textarea
                        autoFocus
                        value={noteValue}
                        onChange={(e) => setNoteValue(e.target.value)}
                        onBlur={() => handleNoteSave(app)}
                        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleNoteSave(app); } if (e.key === "Escape") { setEditingNoteId(null); } }}
                        className="w-full rounded border border-blue-300 px-2 py-1 text-xs text-gray-700 resize-none focus:outline-none focus:ring-1 focus:ring-blue-400"
                        rows={2}
                      />
                    ) : (
                      <span
                        className="text-xs text-gray-500 truncate block cursor-pointer hover:text-blue-600"
                        title="Klicken zum Bearbeiten"
                        onClick={() => { setEditingNoteId(app.id); setNoteValue(app.notes ?? ""); }}
                      >
                        {app.notes ?? <span className="text-gray-300 italic">Notiz hinzufügen…</span>}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                    <div className="flex items-center gap-1.5">
                      {app.job_id && (
                        <Link
                          href={`/dashboard/jobs/${app.job_id}`}
                          className="rounded border border-gray-200 px-2 py-0.5 text-xs text-gray-600 hover:border-gray-400 hover:text-gray-900 whitespace-nowrap"
                        >
                          → Job
                        </Link>
                      )}
                      {app.status !== "rejected" && app.status !== "withdrawn" && app.status !== "offer" && (
                        <button
                          onClick={() => setInterviewApp(app)}
                          className="rounded border border-blue-200 bg-blue-50 px-2 py-0.5 text-xs text-blue-700 hover:bg-blue-100 whitespace-nowrap"
                        >
                          📅 Interview
                        </button>
                      )}
                      {(app.status === "interview" || app.status === "offer") && (
                        <button
                          onClick={() => setEvaluationApp(app)}
                          className="rounded border border-purple-200 bg-purple-50 px-2 py-0.5 text-xs text-purple-700 hover:bg-purple-100 whitespace-nowrap"
                        >
                          Bewerten
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page === 1}
            className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:border-gray-300 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            ← Zurück
          </button>
          <span className="text-sm text-gray-500">
            Seite {page} von {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
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

      {interviewApp && (
        <InterviewModal
          applicationId={interviewApp.id}
          candidateName={interviewApp.candidate_name}
          onClose={() => setInterviewApp(null)}
          onSuccess={() => setInterviewApp(null)}
        />
      )}

      {evaluationApp && (
        <InterviewEvaluationModal
          applicationId={evaluationApp.id}
          candidateName={evaluationApp.candidate_name}
          jobTitle={evaluationApp.job_title}
          onClose={() => setEvaluationApp(null)}
        />
      )}
    </div>
  );
}
