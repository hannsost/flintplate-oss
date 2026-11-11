"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Plus,
  ChevronLeft,
  ChevronRight,
  Pencil,
  Trash2,
  X,
  Calendar,
  MapPin,
  Building2,
  Clock,
  User,
  RefreshCw,
  CheckCircle2,
  PlayCircle,
  XCircle,
} from "lucide-react";
import { auth } from "@/lib/auth";
import {
  assignmentsApi,
  AssignmentWithWorker,
  WorkAssignmentCreate,
  WorkAssignmentUpdate,
  WorkerListRead,
  workerManagementApi,
} from "@/lib/api";

// ── Helpers ──────────────────────────────────────────────────────────────────

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

function fmtDate(iso: string): string {
  return new Date(iso + "T00:00:00").toLocaleDateString("de-DE", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
  });
}

function fmtTime(t: string | null): string {
  if (!t) return "";
  return t.slice(0, 5);
}

// ── Status ───────────────────────────────────────────────────────────────────

const STATUSES = ["planned", "confirmed", "active", "completed", "cancelled"] as const;
type AssignmentStatus = (typeof STATUSES)[number];

const STATUS_META: Record<AssignmentStatus, { label: string; color: string; bg: string; icon: React.ReactNode }> = {
  planned:   { label: "Geplant",        color: "text-gray-700",    bg: "bg-gray-100",    icon: <Calendar className="w-3 h-3" /> },
  confirmed: { label: "Bestätigt",      color: "text-blue-700",    bg: "bg-blue-100",    icon: <CheckCircle2 className="w-3 h-3" /> },
  active:    { label: "Aktiv",          color: "text-green-700",   bg: "bg-green-100",   icon: <PlayCircle className="w-3 h-3" /> },
  completed: { label: "Abgeschlossen",  color: "text-blue-700", bg: "bg-blue-100", icon: <CheckCircle2 className="w-3 h-3" /> },
  cancelled: { label: "Storniert",      color: "text-red-600",     bg: "bg-red-100",     icon: <XCircle className="w-3 h-3" /> },
};

function StatusBadge({ status }: { status: string }) {
  const meta = STATUS_META[status as AssignmentStatus] ?? STATUS_META.planned;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium ${meta.bg} ${meta.color}`}>
      {meta.icon}
      {meta.label}
    </span>
  );
}

// ── Assignment Drawer ─────────────────────────────────────────────────────────

interface DrawerProps {
  mode: "create" | "edit";
  initial?: AssignmentWithWorker;
  workers: WorkerListRead[];
  onSave: (data: WorkAssignmentCreate | WorkAssignmentUpdate, id?: string) => Promise<void>;
  onClose: () => void;
  saving: boolean;
}

function AssignmentDrawer({ mode, initial, workers, onSave, onClose, saving }: DrawerProps) {
  const [workerId, setWorkerId] = useState(initial?.worker_id ?? "");
  const [startDate, setStartDate] = useState(initial?.start_date ?? "");
  const [endDate, setEndDate] = useState(initial?.end_date ?? "");
  const [shiftStart, setShiftStart] = useState(initial?.shift_start ? fmtTime(initial.shift_start) : "");
  const [shiftEnd, setShiftEnd] = useState(initial?.shift_end ? fmtTime(initial.shift_end) : "");
  const [company, setCompany] = useState(initial?.customer_company ?? "");
  const [location, setLocation] = useState(initial?.location ?? "");
  const [role, setRole] = useState(initial?.role_description ?? "");
  const [notes, setNotes] = useState(initial?.notes ?? "");
  const [status, setStatus] = useState<AssignmentStatus>((initial?.status as AssignmentStatus) ?? "planned");

  function handleSubmit() {
    if (!startDate || !endDate) return;
    if (mode === "create") {
      onSave({
        worker_id: workerId,
        start_date: startDate as unknown as Date,
        end_date: endDate as unknown as Date,
        shift_start: shiftStart ? (shiftStart as unknown as Date) : undefined,
        shift_end: shiftEnd ? (shiftEnd as unknown as Date) : undefined,
        customer_company: company || undefined,
        location: location || undefined,
        role_description: role || undefined,
        notes: notes || undefined,
        status,
      } as unknown as WorkAssignmentCreate);
    } else {
      onSave({
        start_date: startDate as unknown as Date,
        end_date: endDate as unknown as Date,
        shift_start: shiftStart ? (shiftStart as unknown as Date) : null,
        shift_end: shiftEnd ? (shiftEnd as unknown as Date) : null,
        customer_company: company || null,
        location: location || null,
        role_description: role || null,
        notes: notes || null,
        status,
      } as unknown as WorkAssignmentUpdate, initial?.id);
    }
  }

  const canSubmit = startDate && endDate && (mode === "edit" || !!workerId);

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      <div className="fixed inset-y-0 right-0 z-50 w-full max-w-md bg-white shadow-2xl flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100">
          <h2 className="text-base font-semibold text-gray-900">
            {mode === "create" ? "Neuer Einsatz" : "Einsatz bearbeiten"}
          </h2>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Form */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          {/* Worker */}
          {mode === "create" && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Mitarbeiter *</label>
              <select
                value={workerId}
                onChange={(e) => setWorkerId(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="">— Mitarbeiter wählen —</option>
                {workers.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.full_name ?? w.email}
                  </option>
                ))}
              </select>
            </div>
          )}

          {/* Dates */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Von *</label>
              <input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Bis *</label>
              <input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                min={startDate}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          {/* Shift times */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Schichtbeginn</label>
              <input
                type="time"
                value={shiftStart}
                onChange={(e) => setShiftStart(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Schichtende</label>
              <input
                type="time"
                value={shiftEnd}
                onChange={(e) => setShiftEnd(e.target.value)}
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          {/* Status */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Status</label>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value as AssignmentStatus)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {STATUSES.map((s) => (
                <option key={s} value={s}>{STATUS_META[s].label}</option>
              ))}
            </select>
          </div>

          {/* Customer / location / role */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Kundenfirma</label>
            <input
              type="text"
              value={company}
              onChange={(e) => setCompany(e.target.value)}
              placeholder="z. B. Muster GmbH"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Einsatzort</label>
            <input
              type="text"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              placeholder="z. B. Werkshalle 3, München"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Tätigkeit</label>
            <input
              type="text"
              value={role}
              onChange={(e) => setRole(e.target.value)}
              placeholder="z. B. Lagerhelfer, Produktionsmitarbeiter"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Interne Notiz</label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={3}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-gray-100 flex gap-2">
          <button
            onClick={onClose}
            className="flex-1 py-2 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200"
          >
            Abbrechen
          </button>
          <button
            disabled={!canSubmit || saving}
            onClick={handleSubmit}
            className="flex-1 py-2 text-sm text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-40"
          >
            {saving ? "Speichern..." : mode === "create" ? "Erstellen" : "Speichern"}
          </button>
        </div>
      </div>
    </>
  );
}

// ── Assignment Row ────────────────────────────────────────────────────────────

function AssignmentRow({
  a,
  onEdit,
  onDelete,
}: {
  a: AssignmentWithWorker;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const isSingle = a.start_date === a.end_date;
  const dateStr = isSingle
    ? fmtDate(a.start_date ?? "")
    : `${fmtDate(a.start_date ?? "")} – ${fmtDate(a.end_date ?? "")}`;

  return (
    <tr className="hover:bg-gray-50 transition-colors">
      <td className="px-4 py-3">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-full bg-blue-100 flex items-center justify-center flex-shrink-0">
            <User className="w-3.5 h-3.5 text-blue-600" />
          </div>
          <div>
            <p className="text-sm font-medium text-gray-900 leading-tight">
              {a.worker_name ?? "–"}
            </p>
            <p className="text-xs text-gray-400">{a.worker_email}</p>
          </div>
        </div>
      </td>
      <td className="px-4 py-3 text-sm text-gray-700">{dateStr}</td>
      <td className="px-4 py-3 text-sm text-gray-500">
        {a.shift ?? (a.shift_start && a.shift_end
          ? `${fmtTime(a.shift_start)} – ${fmtTime(a.shift_end)}`
          : "–")}
      </td>
      <td className="px-4 py-3 text-sm text-gray-700">
        {a.activity ?? a.role_description ?? "–"}
      </td>
      <td className="px-4 py-3 text-sm text-gray-500">
        {a.customer ?? a.customer_company ?? "–"}
      </td>
      <td className="px-4 py-3 text-sm text-gray-500">
        <span className="flex items-center gap-1">
          {a.location ? (
            <>
              <MapPin className="w-3.5 h-3.5 flex-shrink-0" />
              {a.location}
            </>
          ) : "–"}
        </span>
      </td>
      <td className="px-4 py-3">
        <StatusBadge status={a.status} />
      </td>
      <td className="px-4 py-3">
        <div className="flex items-center gap-1">
          <button
            onClick={onEdit}
            className="p-1.5 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50"
            title="Bearbeiten"
          >
            <Pencil className="w-4 h-4" />
          </button>
          <button
            onClick={onDelete}
            className="p-1.5 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-50"
            title="Löschen"
          >
            <Trash2 className="w-4 h-4" />
          </button>
        </div>
      </td>
    </tr>
  );
}

// ── Main Page ────────────────────────────────────────────────────────────────

export default function AssignmentsPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [month, setMonth] = useState(currentMonth());
  const [assignments, setAssignments] = useState<AssignmentWithWorker[]>([]);
  const [workers, setWorkers] = useState<WorkerListRead[]>([]);
  const [loading, setLoading] = useState(true);

  // Drawer
  const [drawer, setDrawer] = useState<{ mode: "create" | "edit"; item?: AssignmentWithWorker } | null>(null);
  const [saving, setSaving] = useState(false);

  // Status filter
  const [statusFilter, setStatusFilter] = useState("all");

  // Auth
  useEffect(() => {
    const t = auth.getAccess();
    if (!t) { router.replace("/login"); return; }
    setToken(t);
  }, [router]);

  // Load data
  const loadAssignments = useCallback(async (t: string) => {
    setLoading(true);
    try {
      const [data, ws] = await Promise.all([
        assignmentsApi.list(t, { month, status: statusFilter !== "all" ? statusFilter : undefined }),
        workerManagementApi.list(t),
      ]);
      setAssignments(data);
      setWorkers(ws.filter((w) => w.settings?.is_active));
    } catch {
      setAssignments([]);
    } finally {
      setLoading(false);
    }
  }, [month, statusFilter]);

  useEffect(() => {
    if (token) loadAssignments(token);
  }, [token, loadAssignments]);

  // Save (create or edit)
  async function handleSave(data: WorkAssignmentCreate | WorkAssignmentUpdate, id?: string) {
    if (!token) return;
    setSaving(true);
    try {
      if (id) {
        await assignmentsApi.update(token, id, data as WorkAssignmentUpdate);
      } else {
        await assignmentsApi.create(token, data as WorkAssignmentCreate);
      }
      setDrawer(null);
      await loadAssignments(token);
    } catch {
      // silently ignore
    } finally {
      setSaving(false);
    }
  }

  // Delete
  async function handleDelete(id: string) {
    if (!token) return;
    if (!confirm("Einsatz wirklich löschen?")) return;
    try {
      await assignmentsApi.delete(token, id);
      setAssignments((prev) => prev.filter((a) => a.id !== id));
    } catch {
      // silently ignore
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-semibold text-gray-900">Einsatzplanung</h1>
          <p className="text-sm text-gray-500 mt-0.5">Mitarbeitereinsätze planen und verwalten</p>
        </div>
        <button
          onClick={() => setDrawer({ mode: "create" })}
          className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-xl hover:bg-blue-700 shadow-sm"
        >
          <Plus className="w-4 h-4" />
          Neuer Einsatz
        </button>
      </div>

      {/* Filters */}
      <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 flex flex-wrap items-center gap-3 mb-4">
        {/* Month */}
        <div className="flex items-center gap-1">
          <button
            onClick={() => setMonth(prevMonth(month))}
            className="p-1 rounded hover:bg-gray-100 text-gray-500"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-sm font-medium text-gray-700 w-36 text-center">
            {monthLabel(month)}
          </span>
          <button
            onClick={() => setMonth(nextMonth(month))}
            className="p-1 rounded hover:bg-gray-100 text-gray-500"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>

        {/* Status filter */}
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="text-sm border border-gray-300 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="all">Alle Status</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>{STATUS_META[s].label}</option>
          ))}
        </select>

        <div className="flex-1" />

        <button
          onClick={() => token && loadAssignments(token)}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-40"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
          Aktualisieren
        </button>
      </div>

      {/* Table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        {loading ? (
          <div className="flex items-center justify-center h-48 text-gray-400 text-sm gap-2">
            <RefreshCw className="w-4 h-4 animate-spin" />
            Lade Einsätze...
          </div>
        ) : assignments.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 text-gray-400 gap-2">
            <Calendar className="w-8 h-8 text-gray-200" />
            <p className="text-sm">Keine Einsätze in diesem Zeitraum</p>
            <button
              onClick={() => setDrawer({ mode: "create" })}
              className="mt-1 text-sm text-blue-600 hover:underline"
            >
              Ersten Einsatz erstellen
            </button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px]">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50">
                  {["Mitarbeiter", "Zeitraum", "Schicht", "Tätigkeit", "Kunde", "Ort", "Status", ""].map((h) => (
                    <th
                      key={h}
                      className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {assignments.map((a) => (
                  <AssignmentRow
                    key={a.id}
                    a={a}
                    onEdit={() => setDrawer({ mode: "edit", item: a })}
                    onDelete={() => handleDelete(a.id)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {!loading && assignments.length > 0 && (
        <p className="text-xs text-gray-400 mt-2 text-right">{assignments.length} Einsätze</p>
      )}

      {/* Drawer */}
      {drawer && (
        <AssignmentDrawer
          mode={drawer.mode}
          initial={drawer.item}
          workers={workers}
          onSave={handleSave}
          onClose={() => setDrawer(null)}
          saving={saving}
        />
      )}
    </div>
  );
}
