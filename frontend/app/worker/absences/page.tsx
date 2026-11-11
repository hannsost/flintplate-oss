"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Plus, X, Calendar, Clock, CheckCircle2, XCircle,
  AlertCircle, Sun, Thermometer, ChevronLeft, ChevronRight,
} from "lucide-react";
import { auth } from "@/lib/auth";
import { absencesApi, AbsenceRead, AbsenceSummary } from "@/lib/api";

// ── Constants ─────────────────────────────────────────────────────────────────

const TYPE_META: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  vacation: { label: "Urlaub",               color: "bg-blue-100 text-blue-700",   icon: <Sun className="w-3.5 h-3.5" /> },
  sick:     { label: "Krankmeldung",          color: "bg-red-100 text-red-700",     icon: <Thermometer className="w-3.5 h-3.5" /> },
  unpaid:   { label: "Unbezahlt",             color: "bg-gray-100 text-gray-700",   icon: <Calendar className="w-3.5 h-3.5" /> },
  special:  { label: "Sonderurlaub",          color: "bg-purple-100 text-purple-700", icon: <Calendar className="w-3.5 h-3.5" /> },
  other:    { label: "Sonstiges",             color: "bg-yellow-100 text-yellow-700", icon: <Calendar className="w-3.5 h-3.5" /> },
};

const STATUS_META: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  pending:   { label: "Ausstehend",  color: "bg-amber-100 text-amber-700",  icon: <Clock className="w-3 h-3" /> },
  approved:  { label: "Genehmigt",   color: "bg-green-100 text-green-700",  icon: <CheckCircle2 className="w-3 h-3" /> },
  rejected:  { label: "Abgelehnt",   color: "bg-red-100 text-red-700",      icon: <XCircle className="w-3 h-3" /> },
  cancelled: { label: "Storniert",   color: "bg-gray-100 text-gray-500",    icon: <XCircle className="w-3 h-3" /> },
};

function TypeBadge({ type }: { type: string }) {
  const m = TYPE_META[type] ?? TYPE_META.other;
  return <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${m.color}`}>{m.icon}{m.label}</span>;
}

function StatusBadge({ status }: { status: string }) {
  const m = STATUS_META[status] ?? STATUS_META.pending;
  return <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${m.color}`}>{m.icon}{m.label}</span>;
}

function fmtDate(iso: string) {
  return new Date(iso + "T00:00:00").toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function currentYear() { return new Date().getFullYear(); }

// ── New Absence Sheet ─────────────────────────────────────────────────────────

function NewAbsenceSheet({ onSave, onClose, saving }: {
  onSave: (type: string, start: string, end: string, note: string) => void;
  onClose: () => void;
  saving: boolean;
}) {
  const [type, setType] = useState("vacation");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [note, setNote] = useState("");

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      <div className="fixed inset-x-0 bottom-0 z-50 bg-white rounded-t-2xl shadow-2xl p-5 pb-8 md:inset-auto md:top-1/2 md:left-1/2 md:-translate-x-1/2 md:-translate-y-1/2 md:w-full md:max-w-md md:rounded-2xl">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-gray-900">Abwesenheit beantragen</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500"><X className="w-4 h-4" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Art</label>
            <select value={type} onChange={(e) => setType(e.target.value)}
              className="w-full border border-gray-300 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              {Object.entries(TYPE_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Von *</label>
              <input type="date" value={start} onChange={(e) => setStart(e.target.value)}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Bis *</label>
              <input type="date" value={end} onChange={(e) => setEnd(e.target.value)} min={start}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Notiz / Begründung</label>
            <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={3} placeholder="Optional..."
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
        </div>
        <div className="flex gap-2 mt-4">
          <button onClick={onClose} className="flex-1 py-2.5 text-sm text-gray-600 bg-gray-100 rounded-xl hover:bg-gray-200">Abbrechen</button>
          <button disabled={!start || !end || saving} onClick={() => onSave(type, start, end, note)}
            className="flex-1 py-2.5 text-sm text-white bg-blue-600 rounded-xl hover:bg-blue-700 disabled:opacity-40">
            {saving ? "Wird gesendet..." : "Beantragen"}
          </button>
        </div>
      </div>
    </>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function WorkerAbsencesPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [year, setYear] = useState(currentYear());
  const [absences, setAbsences] = useState<AbsenceRead[]>([]);
  const [summary, setSummary] = useState<AbsenceSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const t = auth.getAccess();
    if (!t) { router.replace("/login"); return; }
    setToken(t);
  }, [router]);

  const load = useCallback(async (t: string, y: number) => {
    setLoading(true);
    try {
      const [list, sum] = await Promise.all([
        absencesApi.list(t, { year: y }),
        absencesApi.summary(t, y),
      ]);
      setAbsences(list);
      setSummary(sum);
    } catch { setAbsences([]); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (token) load(token, year); }, [token, year, load]);

  async function handleNew(type: string, start: string, end: string, note: string) {
    if (!token) return;
    setSaving(true);
    try {
      const created = await absencesApi.create(token, { absence_type: type, start_date: start, end_date: end, worker_note: note || undefined });
      setAbsences((prev) => [created, ...prev]);
      setShowNew(false);
      load(token, year);
    } catch { /* ignore */ }
    finally { setSaving(false); }
  }

  async function handleCancel(id: string) {
    if (!token || !confirm("Antrag stornieren?")) return;
    try {
      await absencesApi.cancel(token, id);
      setAbsences((prev) => prev.map((a) => a.id === id ? { ...a, status: "cancelled" } : a));
    } catch { /* ignore */ }
  }

  return (
    <div className="min-h-screen bg-gray-50 p-4 md:p-6">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Meine Abwesenheiten</h1>
            <p className="text-sm text-gray-500 mt-0.5">Urlaub und Abwesenheiten beantragen</p>
          </div>
          <button onClick={() => setShowNew(true)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-xl hover:bg-blue-700">
            <Plus className="w-4 h-4" /> Beantragen
          </button>
        </div>

        {/* Year nav */}
        <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 flex items-center justify-between mb-4">
          <button onClick={() => setYear(y => y - 1)} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500">
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-sm font-semibold text-gray-800">{year}</span>
          <button onClick={() => setYear(y => y + 1)} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500">
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>

        {/* Summary cards */}
        {summary && (
          <div className="grid grid-cols-3 gap-3 mb-5">
            <div className="bg-white border border-gray-200 rounded-xl p-4 text-center">
              <p className="text-2xl font-bold text-blue-600">{summary.vacation_days_approved}</p>
              <p className="text-xs text-gray-500 mt-0.5">Urlaubstage</p>
            </div>
            <div className="bg-white border border-gray-200 rounded-xl p-4 text-center">
              <p className="text-2xl font-bold text-amber-500">{summary.vacation_days_pending}</p>
              <p className="text-xs text-gray-500 mt-0.5">Beantragt</p>
            </div>
            <div className="bg-white border border-gray-200 rounded-xl p-4 text-center">
              <p className="text-2xl font-bold text-red-500">{summary.sick_days_approved}</p>
              <p className="text-xs text-gray-500 mt-0.5">Kranktage</p>
            </div>
          </div>
        )}

        {/* Absence list */}
        {loading ? (
          <div className="flex items-center justify-center h-32 text-gray-400 text-sm">Lade...</div>
        ) : absences.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-32 text-gray-400 gap-2">
            <Calendar className="w-8 h-8 text-gray-200" />
            <p className="text-sm">Keine Abwesenheiten in {year}</p>
          </div>
        ) : (
          <div className="space-y-3">
            {absences.map((a) => (
              <div key={a.id} className="bg-white border border-gray-200 rounded-xl p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <TypeBadge type={a.absence_type} />
                      <StatusBadge status={a.status} />
                    </div>
                    <p className="text-sm font-medium text-gray-900 mt-2">
                      {fmtDate(a.start_date)} – {fmtDate(a.end_date)}
                    </p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {a.working_days} Arbeitstag{a.working_days !== 1 ? "e" : ""}
                    </p>
                    {a.worker_note && (
                      <p className="text-xs text-gray-400 mt-1 italic">&quot;{a.worker_note}&quot;</p>
                    )}
                    {a.reviewer_note && (
                      <p className={`text-xs mt-1 font-medium ${a.status === "rejected" ? "text-red-600" : "text-green-600"}`}>
                        HR: {a.reviewer_note}
                      </p>
                    )}
                  </div>
                  {a.status === "pending" && (
                    <button onClick={() => handleCancel(a.id)}
                      className="p-1.5 rounded-lg text-gray-300 hover:text-red-500 hover:bg-red-50 flex-shrink-0"
                      title="Stornieren">
                      <X className="w-4 h-4" />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {showNew && <NewAbsenceSheet onSave={handleNew} onClose={() => setShowNew(false)} saving={saving} />}
    </div>
  );
}
