"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  CheckCircle2, XCircle, Clock, Sun, Thermometer, Calendar,
  ChevronLeft, ChevronRight, Search, Filter,
} from "lucide-react";
import { auth } from "@/lib/auth";
import { hrAbsencesApi, AbsenceRead } from "@/lib/api";

// ── Constants ─────────────────────────────────────────────────────────────────

const TYPE_META: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  vacation: { label: "Urlaub",       color: "bg-blue-100 text-blue-700",     icon: <Sun className="w-3.5 h-3.5" /> },
  sick:     { label: "Krankmeldung", color: "bg-red-100 text-red-700",       icon: <Thermometer className="w-3.5 h-3.5" /> },
  unpaid:   { label: "Unbezahlt",    color: "bg-gray-100 text-gray-700",     icon: <Calendar className="w-3.5 h-3.5" /> },
  special:  { label: "Sonderurlaub", color: "bg-purple-100 text-purple-700", icon: <Calendar className="w-3.5 h-3.5" /> },
  other:    { label: "Sonstiges",    color: "bg-yellow-100 text-yellow-700", icon: <Calendar className="w-3.5 h-3.5" /> },
};

const STATUS_META: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  pending:   { label: "Ausstehend", color: "bg-amber-100 text-amber-700",  icon: <Clock className="w-3 h-3" /> },
  approved:  { label: "Genehmigt",  color: "bg-green-100 text-green-700",  icon: <CheckCircle2 className="w-3 h-3" /> },
  rejected:  { label: "Abgelehnt",  color: "bg-red-100 text-red-700",      icon: <XCircle className="w-3 h-3" /> },
  cancelled: { label: "Storniert",  color: "bg-gray-100 text-gray-500",    icon: <XCircle className="w-3 h-3" /> },
};

function TypeBadge({ type }: { type: string }) {
  const m = TYPE_META[type] ?? TYPE_META.other;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${m.color}`}>
      {m.icon}{m.label}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const m = STATUS_META[status] ?? STATUS_META.pending;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${m.color}`}>
      {m.icon}{m.label}
    </span>
  );
}

function fmtDate(iso: string) {
  return new Date(iso + "T00:00:00").toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
}

// ── Review Dialog ─────────────────────────────────────────────────────────────

function ReviewDialog({
  absence,
  action,
  onConfirm,
  onClose,
  saving,
}: {
  absence: AbsenceRead;
  action: "approve" | "reject";
  onConfirm: (note: string) => void;
  onClose: () => void;
  saving: boolean;
}) {
  const [note, setNote] = useState("");

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      <div className="fixed z-50 top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white rounded-2xl shadow-2xl p-5 w-full max-w-md">
        <h3 className="text-base font-semibold text-gray-900 mb-1">
          {action === "approve" ? "Abwesenheit genehmigen" : "Abwesenheit ablehnen"}
        </h3>
        <p className="text-sm text-gray-500 mb-4">
          {absence.worker_name ?? absence.worker_email} · {fmtDate(absence.start_date)} – {fmtDate(absence.end_date)} · {absence.working_days} Arbeitstage
        </p>
        <div>
          <label className="block text-xs font-medium text-gray-600 mb-1">
            {action === "reject" ? "Ablehnungsgrund *" : "Notiz (optional)"}
          </label>
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            placeholder={action === "reject" ? "Begründung für die Ablehnung..." : "Optional..."}
            className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div className="flex gap-2 mt-4">
          <button onClick={onClose} className="flex-1 py-2.5 text-sm text-gray-600 bg-gray-100 rounded-xl hover:bg-gray-200">
            Abbrechen
          </button>
          <button
            disabled={(action === "reject" && !note.trim()) || saving}
            onClick={() => onConfirm(note)}
            className={`flex-1 py-2.5 text-sm text-white rounded-xl disabled:opacity-40 ${
              action === "approve" ? "bg-green-600 hover:bg-green-700" : "bg-red-600 hover:bg-red-700"
            }`}
          >
            {saving ? "Wird gespeichert..." : action === "approve" ? "Genehmigen" : "Ablehnen"}
          </button>
        </div>
      </div>
    </>
  );
}

// ── Detail Panel ──────────────────────────────────────────────────────────────

function DetailPanel({
  absence,
  onApprove,
  onReject,
  onCancel,
  saving,
}: {
  absence: AbsenceRead;
  onApprove: () => void;
  onReject: () => void;
  onCancel: () => void;
  saving: boolean;
}) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5 h-fit">
      <div className="flex items-start justify-between gap-3 mb-4">
        <div>
          <p className="text-base font-semibold text-gray-900">
            {absence.worker_name ?? absence.worker_email}
          </p>
          <p className="text-xs text-gray-400">{absence.worker_email}</p>
        </div>
        <StatusBadge status={absence.status} />
      </div>

      <div className="space-y-3 mb-5">
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-500">Art</span>
          <TypeBadge type={absence.absence_type} />
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-500">Zeitraum</span>
          <span className="text-sm font-medium text-gray-800">
            {fmtDate(absence.start_date)} – {fmtDate(absence.end_date)}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-xs text-gray-500">Arbeitstage</span>
          <span className="text-sm font-medium text-gray-800">{absence.working_days}</span>
        </div>
        {absence.worker_note && (
          <div>
            <p className="text-xs text-gray-500 mb-1">Mitarbeiter-Notiz</p>
            <p className="text-sm text-gray-700 italic">&quot;{absence.worker_note}&quot;</p>
          </div>
        )}
        {absence.reviewer_note && (
          <div>
            <p className="text-xs text-gray-500 mb-1">HR-Notiz</p>
            <p className={`text-sm font-medium ${absence.status === "rejected" ? "text-red-600" : "text-green-600"}`}>
              {absence.reviewer_note}
            </p>
          </div>
        )}
        {absence.reviewed_by_name && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-gray-500">Bearbeitet von</span>
            <span className="text-xs text-gray-600">{absence.reviewed_by_name}</span>
          </div>
        )}
      </div>

      {absence.status === "pending" && (
        <div className="flex gap-2">
          <button
            disabled={saving}
            onClick={onReject}
            className="flex-1 py-2 text-sm text-red-600 bg-red-50 rounded-xl hover:bg-red-100 disabled:opacity-40"
          >
            Ablehnen
          </button>
          <button
            disabled={saving}
            onClick={onApprove}
            className="flex-1 py-2 text-sm text-white bg-green-600 rounded-xl hover:bg-green-700 disabled:opacity-40"
          >
            Genehmigen
          </button>
        </div>
      )}
      {(absence.status === "approved" || absence.status === "pending") && (
        <button
          disabled={saving}
          onClick={onCancel}
          className="w-full mt-2 py-2 text-sm text-gray-500 bg-gray-100 rounded-xl hover:bg-gray-200 disabled:opacity-40"
        >
          Stornieren
        </button>
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

function currentYear() { return new Date().getFullYear(); }

export default function HRAbsencesPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [year, setYear] = useState(currentYear());
  const [absences, setAbsences] = useState<AbsenceRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState<AbsenceRead | null>(null);
  const [saving, setSaving] = useState(false);
  const [reviewTarget, setReviewTarget] = useState<{ absence: AbsenceRead; action: "approve" | "reject" } | null>(null);

  // Filters
  const [statusFilter, setStatusFilter] = useState("");
  const [typeFilter, setTypeFilter] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    const t = auth.getAccess();
    if (!t) { router.replace("/login"); return; }
    setToken(t);
  }, [router]);

  const load = useCallback(async (t: string, y: number) => {
    setLoading(true);
    try {
      const list = await hrAbsencesApi.list(t, { year: y });
      setAbsences(list);
    } catch { setAbsences([]); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (token) load(token, year); }, [token, year, load]);

  const filtered = absences.filter((a) => {
    if (statusFilter && a.status !== statusFilter) return false;
    if (typeFilter && a.absence_type !== typeFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      if (
        !a.worker_name?.toLowerCase().includes(q) &&
        !a.worker_email.toLowerCase().includes(q)
      ) return false;
    }
    return true;
  });

  async function doReview(absence: AbsenceRead, action: "approve" | "reject", note: string) {
    if (!token) return;
    setSaving(true);
    try {
      const updated = await hrAbsencesApi.review(token, absence.id, action, note || undefined);
      setAbsences((prev) => prev.map((a) => a.id === updated.id ? updated : a));
      if (selected?.id === updated.id) setSelected(updated);
      setReviewTarget(null);
    } catch { /* ignore */ }
    finally { setSaving(false); }
  }

  async function doCancel(absence: AbsenceRead) {
    if (!token || !confirm("Abwesenheit stornieren?")) return;
    setSaving(true);
    try {
      await hrAbsencesApi.cancel(token, absence.id);
      const updated = { ...absence, status: "cancelled" };
      setAbsences((prev) => prev.map((a) => a.id === absence.id ? updated : a));
      if (selected?.id === absence.id) setSelected(updated);
    } catch { /* ignore */ }
    finally { setSaving(false); }
  }

  const pendingCount = absences.filter((a) => a.status === "pending").length;

  return (
    <div className="min-h-screen bg-gray-50 p-4 md:p-6">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Abwesenheiten</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              Urlaubsanträge und Abwesenheiten verwalten
              {pendingCount > 0 && (
                <span className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700">
                  {pendingCount} offen
                </span>
              )}
            </p>
          </div>
        </div>

        {/* Filters */}
        <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 flex flex-wrap items-center gap-3 mb-5">
          {/* Year nav */}
          <div className="flex items-center gap-1">
            <button onClick={() => setYear(y => y - 1)} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500">
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="text-sm font-semibold text-gray-800 w-10 text-center">{year}</span>
            <button onClick={() => setYear(y => y + 1)} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500">
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>

          <div className="h-5 w-px bg-gray-200" />

          {/* Search */}
          <div className="relative flex-1 min-w-[160px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Mitarbeiter suchen..."
              className="w-full pl-8 pr-3 py-2 text-sm border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          {/* Status filter */}
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Alle Status</option>
            <option value="pending">Ausstehend</option>
            <option value="approved">Genehmigt</option>
            <option value="rejected">Abgelehnt</option>
            <option value="cancelled">Storniert</option>
          </select>

          {/* Type filter */}
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="">Alle Arten</option>
            <option value="vacation">Urlaub</option>
            <option value="sick">Krankmeldung</option>
            <option value="unpaid">Unbezahlt</option>
            <option value="special">Sonderurlaub</option>
            <option value="other">Sonstiges</option>
          </select>
        </div>

        {/* Content */}
        <div className="flex gap-5">
          {/* List */}
          <div className="flex-1 min-w-0">
            {loading ? (
              <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Lade...</div>
            ) : filtered.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-40 text-gray-400 gap-2">
                <Calendar className="w-8 h-8 text-gray-200" />
                <p className="text-sm">Keine Abwesenheiten gefunden</p>
              </div>
            ) : (
              <div className="space-y-2">
                {filtered.map((a) => (
                  <button
                    key={a.id}
                    onClick={() => setSelected(selected?.id === a.id ? null : a)}
                    className={`w-full text-left bg-white border rounded-xl p-4 transition-colors ${
                      selected?.id === a.id
                        ? "border-blue-400 ring-1 ring-blue-400"
                        : "border-gray-200 hover:border-gray-300"
                    }`}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap mb-1">
                          <span className="text-sm font-medium text-gray-900 truncate">
                            {a.worker_name ?? a.worker_email}
                          </span>
                          {a.status === "pending" && (
                            <span className="w-1.5 h-1.5 rounded-full bg-amber-400 flex-shrink-0" />
                          )}
                        </div>
                        <div className="flex items-center gap-2 flex-wrap">
                          <TypeBadge type={a.absence_type} />
                          <StatusBadge status={a.status} />
                        </div>
                        <p className="text-xs text-gray-500 mt-1.5">
                          {fmtDate(a.start_date)} – {fmtDate(a.end_date)} · {a.working_days} Arbeitstag{a.working_days !== 1 ? "e" : ""}
                        </p>
                      </div>
                      {a.status === "pending" && (
                        <div className="flex gap-1.5 flex-shrink-0">
                          <button
                            onClick={(e) => { e.stopPropagation(); setReviewTarget({ absence: a, action: "reject" }); }}
                            className="px-3 py-1.5 text-xs text-red-600 bg-red-50 rounded-lg hover:bg-red-100"
                          >
                            Ablehnen
                          </button>
                          <button
                            onClick={(e) => { e.stopPropagation(); setReviewTarget({ absence: a, action: "approve" }); }}
                            className="px-3 py-1.5 text-xs text-white bg-green-600 rounded-lg hover:bg-green-700"
                          >
                            Genehmigen
                          </button>
                        </div>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Detail panel */}
          {selected && (
            <div className="w-80 flex-shrink-0">
              <DetailPanel
                absence={selected}
                onApprove={() => setReviewTarget({ absence: selected, action: "approve" })}
                onReject={() => setReviewTarget({ absence: selected, action: "reject" })}
                onCancel={() => doCancel(selected)}
                saving={saving}
              />
            </div>
          )}
        </div>
      </div>

      {/* Review Dialog */}
      {reviewTarget && (
        <ReviewDialog
          absence={reviewTarget.absence}
          action={reviewTarget.action}
          onConfirm={(note) => doReview(reviewTarget.absence, reviewTarget.action, note)}
          onClose={() => setReviewTarget(null)}
          saving={saving}
        />
      )}
    </div>
  );
}
