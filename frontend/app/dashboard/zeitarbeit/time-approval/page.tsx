"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Clock,
  CheckCircle2,
  XCircle,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
  User,
  Download,
  RefreshCw,
  Filter,
} from "lucide-react";
import { auth } from "@/lib/auth";
import {
  timeApprovalApi,
  PendingEntryRead,
  TimeBulkDecision,
} from "@/lib/api";

// ── Helpers ──────────────────────────────────────────────────────────────────

function fmtTime(iso: string | null): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleTimeString("de-DE", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString("de-DE", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
  });
}

function fmtMinutes(min: number | null): string {
  if (min === null || min === undefined) return "–";
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

function monthLabel(ym: string): string {
  const [y, m] = ym.split("-");
  return new Date(Number(y), Number(m) - 1).toLocaleDateString("de-DE", {
    month: "long",
    year: "numeric",
  });
}

function prevMonth(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m - 2);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function nextMonth(ym: string): string {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

// ── Status Badge ─────────────────────────────────────────────────────────────

const STATUS_META: Record<
  string,
  { label: string; color: string; icon: React.ReactNode }
> = {
  submitted: {
    label: "Eingereicht",
    color: "bg-blue-100 text-blue-700",
    icon: <Clock className="w-3.5 h-3.5" />,
  },
  approved: {
    label: "Freigegeben",
    color: "bg-green-100 text-green-700",
    icon: <CheckCircle2 className="w-3.5 h-3.5" />,
  },
  rejected: {
    label: "Abgelehnt",
    color: "bg-red-100 text-red-700",
    icon: <XCircle className="w-3.5 h-3.5" />,
  },
  correction_requested: {
    label: "Korrektur",
    color: "bg-amber-100 text-amber-700",
    icon: <AlertCircle className="w-3.5 h-3.5" />,
  },
  draft: {
    label: "Entwurf",
    color: "bg-gray-100 text-gray-600",
    icon: <Clock className="w-3.5 h-3.5" />,
  },
};

function StatusBadge({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? STATUS_META.draft;
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${meta.color}`}
    >
      {meta.icon}
      {meta.label}
    </span>
  );
}

// ── Rejection Dialog ──────────────────────────────────────────────────────────

function RejectDialog({
  onConfirm,
  onCancel,
  count,
}: {
  onConfirm: (note: string) => void;
  onCancel: () => void;
  count: number;
}) {
  const [note, setNote] = useState("");
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-md p-6">
        <h3 className="text-base font-semibold text-gray-900 mb-1">
          {count > 1 ? `${count} Einträge ablehnen` : "Eintrag ablehnen"}
        </h3>
        <p className="text-sm text-gray-500 mb-4">
          Bitte gib einen Grund an (wird dem Mitarbeiter angezeigt).
        </p>
        <textarea
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm resize-none h-24 focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="z. B. Fehlende Pausenangabe, Stunden nicht plausibel..."
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
        <div className="flex justify-end gap-2 mt-4">
          <button
            onClick={onCancel}
            className="px-4 py-2 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200"
          >
            Abbrechen
          </button>
          <button
            disabled={!note.trim()}
            onClick={() => onConfirm(note.trim())}
            className="px-4 py-2 text-sm text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-40"
          >
            Ablehnen
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Entry Row ────────────────────────────────────────────────────────────────

function EntryRow({
  entry,
  selected,
  onSelect,
  onApprove,
  onReject,
  actionLoading,
}: {
  entry: PendingEntryRead;
  selected: boolean;
  onSelect: () => void;
  onApprove: () => void;
  onReject: () => void;
  actionLoading: boolean;
}) {
  return (
    <tr className="hover:bg-gray-50 transition-colors">
      <td className="px-4 py-3 w-10">
        <input
          type="checkbox"
          checked={selected}
          onChange={onSelect}
          className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
        />
      </td>
      {/* Worker */}
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
            <User className="w-3.5 h-3.5 text-blue-600" />
          </div>
          <div>
            <p className="text-sm font-medium text-gray-900 leading-tight">
              {entry.worker_name ?? "–"}
            </p>
            <p className="text-xs text-gray-400">{entry.worker_email}</p>
          </div>
        </div>
      </td>
      {/* Date */}
      <td className="px-4 py-3 text-sm text-gray-700">
        {fmtDate(entry.entry_date)}
      </td>
      {/* Time */}
      <td className="px-4 py-3 text-sm text-gray-700">
        {fmtTime(entry.clock_in)} – {fmtTime(entry.clock_out)}
      </td>
      {/* Break */}
      <td className="px-4 py-3 text-sm text-gray-500 text-center">
        {entry.break_minutes > 0 ? `${entry.break_minutes} min` : "–"}
      </td>
      {/* Net */}
      <td className="px-4 py-3 text-sm font-medium text-gray-900 text-right">
        {fmtMinutes(entry.net_minutes)}
      </td>
      {/* Status */}
      <td className="px-4 py-3">
        <StatusBadge status={entry.status} />
      </td>
      {/* Note */}
      <td className="px-4 py-3 max-w-[180px]">
        <p className="text-xs text-gray-500 truncate">
          {entry.worker_note ?? entry.rejection_note ?? "–"}
        </p>
      </td>
      {/* Actions */}
      <td className="px-4 py-3">
        {(entry.status === "submitted" ||
          entry.status === "correction_requested") && (
          <div className="flex items-center gap-1">
            <button
              disabled={actionLoading}
              onClick={onApprove}
              title="Freigeben"
              className="p-1.5 rounded-lg text-green-600 hover:bg-green-50 disabled:opacity-40"
            >
              <CheckCircle2 className="w-4 h-4" />
            </button>
            <button
              disabled={actionLoading}
              onClick={onReject}
              title="Ablehnen"
              className="p-1.5 rounded-lg text-red-600 hover:bg-red-50 disabled:opacity-40"
            >
              <XCircle className="w-4 h-4" />
            </button>
          </div>
        )}
      </td>
    </tr>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function TimeApprovalPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);

  // Data
  const [entries, setEntries] = useState<PendingEntryRead[]>([]);
  const [loading, setLoading] = useState(true);

  // Filters
  // Do not hide older entries by default; recruiters can narrow the overview
  // to a month explicitly.
  const [month, setMonth] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("pending"); // "pending" | "all" | specific status
  const [workerFilter, setWorkerFilter] = useState("");

  // Selection
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Action state
  const [actionLoading, setActionLoading] = useState(false);
  const [rejectDialog, setRejectDialog] = useState<{
    ids: string[];
  } | null>(null);

  // Auth
  useEffect(() => {
    const t = auth.getAccess();
    if (!t) { router.replace("/login"); return; }
    setToken(t);
  }, [router]);

  // Load entries
  const loadEntries = useCallback(async (t: string) => {
    setLoading(true);
    setSelected(new Set());
    try {
      if (statusFilter === "pending") {
        const data = await timeApprovalApi.pending(t, workerFilter || undefined);
        setEntries(data);
      } else {
        const data = await timeApprovalApi.all(t, {
          month: month ?? undefined,
          status: statusFilter === "all" ? undefined : statusFilter,
          worker_id: workerFilter || undefined,
        });
        setEntries(data);
      }
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [month, statusFilter, workerFilter]);

  useEffect(() => {
    if (token) loadEntries(token);
  }, [token, loadEntries]);

  // Selection helpers
  const allSelected =
    entries.length > 0 && entries.every((e) => selected.has(e.id));

  function toggleAll() {
    if (allSelected) {
      setSelected(new Set());
    } else {
      setSelected(new Set(entries.map((e) => e.id)));
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

  // Approve single or bulk
  async function doApprove(ids: string[]) {
    if (!token) return;
    setActionLoading(true);
    try {
      if (ids.length === 1) {
        await timeApprovalApi.decide(token, ids[0], { action: "approve" });
      } else {
        const payload: TimeBulkDecision = { entry_ids: ids, action: "approve" };
        await timeApprovalApi.bulkDecide(token, payload);
      }
      await loadEntries(token);
    } catch {
      // silently ignore – user can retry
    } finally {
      setActionLoading(false);
    }
  }

  // Reject single or bulk (needs note)
  async function doReject(ids: string[], note: string) {
    if (!token) return;
    setRejectDialog(null);
    setActionLoading(true);
    try {
      if (ids.length === 1) {
        await timeApprovalApi.decide(token, ids[0], {
          action: "reject",
          note,
        });
      } else {
        const payload: TimeBulkDecision = {
          entry_ids: ids,
          action: "reject",
          note,
        };
        await timeApprovalApi.bulkDecide(token, payload);
      }
      await loadEntries(token);
    } catch {
      // silently ignore
    } finally {
      setActionLoading(false);
    }
  }

  // CSV export
  async function doExport() {
    if (!token) return;
    try {
      const rows = await timeApprovalApi.export(token, month ?? undefined, workerFilter || undefined);
      if (!rows.length) return;
      const headers = Object.keys(rows[0]);
      const csv = [
        headers.join(";"),
        ...rows.map((r) =>
          headers.map((h) => String(r[h] ?? "")).join(";")
        ),
      ].join("\n");
      const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `stunden-${month ?? "alle"}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      // silently ignore
    }
  }

  // Pending entries eligible for bulk action
  const pendingSelected = Array.from(selected).filter((id) => {
    const e = entries.find((x) => x.id === id);
    return e && (e.status === "submitted" || e.status === "correction_requested");
  });

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-gray-900">
          Stundenfreigabe
        </h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Eingereichte Zeiteinträge prüfen und freigeben
        </p>
      </div>

      {/* Filters Bar */}
      <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 flex flex-wrap items-center gap-3 mb-4">
        {/* Month navigator (only for "all" view) */}
        {statusFilter !== "pending" && month ? (
          <div className="flex items-center gap-1">
            <button
              onClick={() => setMonth(prevMonth(month))}
              className="p-1 rounded hover:bg-gray-100 text-gray-500"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="text-sm font-medium text-gray-700 w-32 text-center">
              {monthLabel(month)}
            </span>
            <button
              onClick={() => setMonth(nextMonth(month))}
              className="p-1 rounded hover:bg-gray-100 text-gray-500"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        ) : statusFilter !== "pending" ? (
          <button
            onClick={() => setMonth(currentMonth())}
            className="text-sm text-gray-600 border border-gray-300 rounded-lg px-3 py-1.5 hover:bg-gray-50"
          >
            Alle Zeiträume
          </button>
        ) : null}

        {statusFilter !== "pending" && month && (
          <button
            onClick={() => setMonth(null)}
            className="text-xs text-gray-500 hover:text-gray-800"
          >
            Zeitraum zurücksetzen
          </button>
        )}

        {/* Status filter */}
        <div className="flex items-center gap-1.5">
          <Filter className="w-4 h-4 text-gray-400" />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="text-sm border border-gray-300 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            <option value="pending">Ausstehend</option>
            <option value="all">Alle</option>
            <option value="submitted">Eingereicht</option>
            <option value="correction_requested">Korrekturanfragen</option>
            <option value="approved">Freigegeben</option>
            <option value="rejected">Abgelehnt</option>
          </select>
        </div>

        {/* Worker filter */}
        <input
          type="text"
          placeholder="Worker-ID filtern..."
          value={workerFilter}
          onChange={(e) => setWorkerFilter(e.target.value)}
          className="text-sm border border-gray-300 rounded-lg px-3 py-1.5 w-52 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />

        <div className="flex-1" />

        {/* Refresh */}
        <button
          onClick={() => token && loadEntries(token)}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-40"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          Aktualisieren
        </button>

        {/* Export */}
        <button
          onClick={doExport}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200"
        >
          <Download className="w-4 h-4" />
          CSV Export
        </button>
      </div>

      {/* Bulk action bar */}
      {pendingSelected.length > 0 && (
        <div className="bg-blue-600 text-white rounded-xl px-4 py-3 flex items-center gap-3 mb-4 shadow-md">
          <span className="text-sm font-medium">
            {pendingSelected.length} ausgewählt
          </span>
          <div className="flex-1" />
          <button
            disabled={actionLoading}
            onClick={() => doApprove(pendingSelected)}
            className="flex items-center gap-1.5 px-4 py-1.5 bg-white text-green-700 text-sm font-medium rounded-lg hover:bg-green-50 disabled:opacity-50"
          >
            <CheckCircle2 className="w-4 h-4" />
            Alle freigeben
          </button>
          <button
            disabled={actionLoading}
            onClick={() => setRejectDialog({ ids: pendingSelected })}
            className="flex items-center gap-1.5 px-4 py-1.5 bg-white text-red-700 text-sm font-medium rounded-lg hover:bg-red-50 disabled:opacity-50"
          >
            <XCircle className="w-4 h-4" />
            Alle ablehnen
          </button>
          <button
            onClick={() => setSelected(new Set())}
            className="ml-1 text-white/70 hover:text-white text-lg leading-none"
          >
            ×
          </button>
        </div>
      )}

      {/* Table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center h-48 text-gray-400 text-sm gap-2">
            <RefreshCw className="w-4 h-4 animate-spin" />
            Lade Einträge...
          </div>
        ) : entries.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-gray-400 gap-2">
            <CheckCircle2 className="w-8 h-8 text-green-300" />
            <p className="text-sm">Keine Einträge vorhanden</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px]">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50">
                  <th className="px-4 py-3 w-10">
                    <input
                      type="checkbox"
                      checked={allSelected}
                      onChange={toggleAll}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                    Mitarbeiter
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                    Datum
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                    Zeit
                  </th>
                  <th className="px-4 py-3 text-center text-xs font-semibold text-gray-500 uppercase tracking-wide">
                    Pause
                  </th>
                  <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">
                    Netto
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                    Status
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                    Notiz
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">
                    Aktionen
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {entries.map((entry) => (
                  <EntryRow
                    key={entry.id}
                    entry={entry}
                    selected={selected.has(entry.id)}
                    onSelect={() => toggleOne(entry.id)}
                    onApprove={() => doApprove([entry.id])}
                    onReject={() => setRejectDialog({ ids: [entry.id] })}
                    actionLoading={actionLoading}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Entry count */}
      {!loading && entries.length > 0 && (
        <p className="text-xs text-gray-400 mt-2 text-right">
          {entries.length} Einträge
        </p>
      )}

      {/* Rejection dialog */}
      {rejectDialog && (
        <RejectDialog
          count={rejectDialog.ids.length}
          onConfirm={(note) => doReject(rejectDialog.ids, note)}
          onCancel={() => setRejectDialog(null)}
        />
      )}
    </div>
  );
}
