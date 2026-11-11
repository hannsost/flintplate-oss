"use client";

import { useEffect, useState } from "react";
import { auth } from "@/lib/auth";
import { zeitarbeitApi, ApiError, type AssignmentRead, type DispositionRead } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { MapPin, X, Search } from "lucide-react";
import { AssignmentModal } from "./AssignmentModal";

const DISP_STATUS_OPTIONS = [
  { value: "suggested",  label: "Vorgeschlagen" },
  { value: "contacted",  label: "Kontaktiert" },
  { value: "confirmed",  label: "Bestätigt" },
  { value: "active",     label: "Im Einsatz" },
  { value: "completed",  label: "Abgeschlossen" },
  { value: "rejected",   label: "Abgelehnt" },
];

const DISP_COLORS: Record<string, string> = {
  suggested:  "bg-gray-100 text-gray-600",
  contacted:  "bg-blue-100 text-blue-700",
  confirmed:  "bg-yellow-100 text-yellow-700",
  active:     "bg-green-100 text-green-700",
  completed:  "bg-purple-100 text-purple-700",
  rejected:   "bg-red-100 text-red-600",
};

interface Props {
  assignment: AssignmentRead;
  onClose: () => void;
  onUpdated: (a: AssignmentRead) => void;
  onDeleted: (id: string) => void;
}

export function DispositionDrawer({ assignment, onClose, onUpdated, onDeleted }: Props) {
  const [dispositions, setDispositions] = useState<DispositionRead[]>([]);
  const [loadingDisp, setLoadingDisp] = useState(false);
  const [matching, setMatching] = useState(false);
  const [editing, setEditing] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [updatingId, setUpdatingId] = useState<string | null>(null);

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) return;
    setLoadingDisp(true);
    zeitarbeitApi.getDispositions(token, assignment.id)
      .then(setDispositions)
      .catch(() => {})
      .finally(() => setLoadingDisp(false));
  }, [assignment.id]);

  async function handleMatch() {
    const token = auth.getAccess();
    if (!token) return;
    setMatching(true);
    try {
      const result = await zeitarbeitApi.runMatching(token, assignment.id);
      setDispositions(result);
    } finally {
      setMatching(false);
    }
  }

  async function handleDispStatusChange(d: DispositionRead, newStatus: string) {
    const token = auth.getAccess();
    if (!token) return;
    setUpdatingId(d.worker_id);
    try {
      const updated = await zeitarbeitApi.updateDisposition(token, assignment.id, d.worker_id, { status: newStatus });
      setDispositions((prev) => prev.map((x) => x.id === updated.id ? updated : x));
    } finally {
      setUpdatingId(null);
    }
  }

  async function handleDelete() {
    if (!confirm(`Auftrag "${assignment.title}" wirklich löschen?`)) return;
    const token = auth.getAccess();
    if (!token) return;
    setDeleting(true);
    try {
      await zeitarbeitApi.deleteAssignment(token, assignment.id);
      onDeleted(assignment.id);
    } finally {
      setDeleting(false);
    }
  }

  const shiftLabel = assignment.shift === "day" ? "Tagschicht" : assignment.shift === "night" ? "Nachtschicht" : assignment.shift === "flexible" ? "Flexibel" : "—";

  return (
    <>
      <div className="fixed inset-0 z-50 flex" onClick={onClose}>
        <div
          className="ml-auto h-full w-full max-w-lg bg-white shadow-2xl overflow-y-auto"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="sticky top-0 bg-white border-b border-gray-100 px-5 py-4 flex items-start justify-between gap-3">
            <div>
              <h2 className="font-semibold text-gray-900">{assignment.title}</h2>
              {assignment.location && <p className="text-sm text-gray-500 mt-0.5 flex items-center gap-1"><MapPin size={12} />{assignment.location}</p>}
            </div>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 mt-0.5"><X size={15} /></button>
          </div>

          <div className="p-5 space-y-6">
            {/* Info grid */}
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="rounded-lg bg-gray-50 border border-gray-100 p-3">
                <p className="text-xs text-gray-400">Schicht</p>
                <p className="font-medium mt-0.5">{shiftLabel}</p>
              </div>
              <div className="rounded-lg bg-gray-50 border border-gray-100 p-3">
                <p className="text-xs text-gray-400">Stundenlohn</p>
                <p className="font-medium mt-0.5">{assignment.hourly_rate ? `${Number(assignment.hourly_rate).toFixed(2)} €/h` : "—"}</p>
              </div>
              {assignment.start_date && (
                <div className="rounded-lg bg-gray-50 border border-gray-100 p-3">
                  <p className="text-xs text-gray-400">Beginn</p>
                  <p className="font-medium mt-0.5">{new Date(assignment.start_date).toLocaleDateString("de-DE")}</p>
                </div>
              )}
              {assignment.end_date && (
                <div className="rounded-lg bg-gray-50 border border-gray-100 p-3">
                  <p className="text-xs text-gray-400">Ende</p>
                  <p className="font-medium mt-0.5">{new Date(assignment.end_date).toLocaleDateString("de-DE")}</p>
                </div>
              )}
              <div className="rounded-lg bg-amber-50 border border-amber-100 p-3 col-span-2">
                <p className="text-xs text-amber-500">AÜG Max. Dauer</p>
                <p className="font-medium text-amber-800 mt-0.5">{assignment.max_duration_months} Monate</p>
              </div>
            </div>

            {/* Skills */}
            {assignment.required_skills.length > 0 && (
              <div>
                <p className="text-xs font-medium text-gray-500 mb-2">Benötigte Skills</p>
                <div className="flex flex-wrap gap-1.5">
                  {assignment.required_skills.map((s) => (
                    <span key={s} className="rounded-full bg-blue-50 border border-blue-200 px-2.5 py-0.5 text-xs text-blue-700">{s}</span>
                  ))}
                </div>
              </div>
            )}

            {/* Dispositions */}
            <div>
              <div className="flex items-center justify-between mb-3">
                <p className="text-xs font-medium text-gray-500">Matching ({dispositions.length})</p>
                <button
                  onClick={handleMatch}
                  disabled={matching}
                  className="text-xs bg-blue-600 hover:bg-blue-700 text-white rounded-md px-3 py-1 transition-colors disabled:opacity-60"
                >
                  {matching ? "Matching läuft…" : <><Search size={13} className="inline mr-1" />Matching starten</>}
                </button>
              </div>

              {loadingDisp ? (
                <div className="flex justify-center py-6">
                  <div className="h-5 w-5 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
                </div>
              ) : dispositions.length === 0 ? (
                <p className="text-sm text-gray-400 text-center py-4">
                  Noch keine Dispositions. Klicke &quot;Matching starten&quot;.
                </p>
              ) : (
                <div className="space-y-2">
                  {dispositions.map((d) => (
                    <div key={d.id} className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="font-medium text-sm text-gray-900">{d.worker_name ?? "Anonym"}</p>
                          {d.worker_headline && <p className="text-xs text-gray-500 truncate">{d.worker_headline}</p>}
                          <div className="mt-1.5 flex flex-wrap gap-1">
                            {d.matched_skills.map((s) => (
                              <span key={s} className="rounded-full bg-green-50 border border-green-200 px-1.5 py-0.5 text-[10px] text-green-700">{s}</span>
                            ))}
                            {d.missing_skills.map((s) => (
                              <span key={s} className="rounded-full bg-red-50 border border-red-200 px-1.5 py-0.5 text-[10px] text-red-600">{s}</span>
                            ))}
                          </div>
                        </div>
                        <div className="shrink-0 text-right space-y-1">
                          <div className={`inline-flex items-center justify-center w-10 h-10 rounded-full text-sm font-bold ${
                            Number(d.score) >= 0.75 ? "bg-green-100 text-green-700" :
                            Number(d.score) >= 0.5 ? "bg-yellow-100 text-yellow-700" :
                            "bg-gray-100 text-gray-500"
                          }`}>
                            {Math.round(Number(d.score) * 100)}%
                          </div>
                          <select
                            value={d.status}
                            disabled={updatingId === d.worker_id}
                            onChange={(e) => handleDispStatusChange(d, e.target.value)}
                            className="block text-xs border border-gray-200 rounded px-1 py-0.5 focus:outline-none"
                          >
                            {DISP_STATUS_OPTIONS.map((o) => (
                              <option key={o.value} value={o.value}>{o.label}</option>
                            ))}
                          </select>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Actions */}
            <div className="flex gap-2 pt-1">
              <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                Bearbeiten
              </Button>
            </div>

            {/* Danger zone */}
            <div className="pt-2 border-t border-gray-100">
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="text-xs text-red-500 hover:text-red-700 transition-colors"
              >
                {deleting ? "Wird gelöscht…" : "Auftrag löschen"}
              </button>
            </div>
          </div>
        </div>
      </div>

      {editing && (
        <AssignmentModal
          initial={assignment}
          onClose={() => setEditing(false)}
          onSaved={(updated) => {
            onUpdated(updated);
            setEditing(false);
          }}
        />
      )}
    </>
  );
}
