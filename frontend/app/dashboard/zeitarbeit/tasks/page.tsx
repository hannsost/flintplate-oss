"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Plus, X, CheckSquare, Square, Clock, AlertTriangle, Search,
} from "lucide-react";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { hrTasksApi, TaskRead, TaskCreate } from "@/lib/api";

// ── Constants ─────────────────────────────────────────────────────────────────

const PRIORITY_META: Record<string, { label: string; color: string; badge: string }> = {
  low:    { label: "Niedrig",  color: "text-gray-500",  badge: "bg-gray-100 text-gray-600" },
  medium: { label: "Mittel",   color: "text-blue-600",  badge: "bg-blue-100 text-blue-700" },
  high:   { label: "Hoch",     color: "text-amber-600", badge: "bg-amber-100 text-amber-700" },
  urgent: { label: "Dringend", color: "text-red-600",   badge: "bg-red-100 text-red-700" },
};

const STATUS_META: Record<string, { label: string; color: string }> = {
  open:        { label: "Offen",       color: "bg-gray-100 text-gray-600" },
  in_progress: { label: "In Arbeit",   color: "bg-blue-100 text-blue-700" },
  done:        { label: "Erledigt",    color: "bg-green-100 text-green-700" },
  cancelled:   { label: "Abgebrochen", color: "bg-gray-100 text-gray-400" },
};

function fmtDate(iso: string) {
  return new Date(iso + "T00:00:00").toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function isOverdue(dueDate: string | null, status: string): boolean {
  if (!dueDate || status === "done" || status === "cancelled") return false;
  return new Date(dueDate + "T23:59:59") < new Date();
}

// ── Create Task Dialog ────────────────────────────────────────────────────────

function CreateTaskDialog({
  workers,
  onSave,
  onClose,
  saving,
}: {
  workers: { id: string; name: string; email: string }[];
  onSave: (body: TaskCreate) => void;
  onClose: () => void;
  saving: boolean;
}) {
  const [form, setForm] = useState<TaskCreate>({
    assigned_to: "",
    title: "",
    priority: "medium",
  });

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      <div className="fixed z-50 top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white rounded-2xl shadow-2xl p-5 w-full max-w-md">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-gray-900">Aufgabe erstellen</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500"><X className="w-4 h-4" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Mitarbeiter *</label>
            <select value={form.assigned_to} onChange={(e) => setForm(f => ({ ...f, assigned_to: e.target.value }))}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="">Auswählen...</option>
              {workers.map((w) => <option key={w.id} value={w.id}>{w.name || w.email}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Titel *</label>
            <input value={form.title} onChange={(e) => setForm(f => ({ ...f, title: e.target.value }))}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Was muss erledigt werden?" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Beschreibung</label>
            <textarea value={form.description ?? ""} onChange={(e) => setForm(f => ({ ...f, description: e.target.value || undefined }))}
              rows={2} placeholder="Optional..."
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Priorität</label>
              <select value={form.priority} onChange={(e) => setForm(f => ({ ...f, priority: e.target.value }))}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                {Object.entries(PRIORITY_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Fälligkeit</label>
              <input type="date" value={form.due_date ?? ""} onChange={(e) => setForm(f => ({ ...f, due_date: e.target.value || undefined }))}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>
        </div>
        <div className="flex gap-2 mt-4">
          <button onClick={onClose} className="flex-1 py-2.5 text-sm text-gray-600 bg-gray-100 rounded-xl hover:bg-gray-200">Abbrechen</button>
          <button disabled={!form.assigned_to || !form.title.trim() || saving} onClick={() => onSave(form)}
            className="flex-1 py-2.5 text-sm text-white bg-blue-600 rounded-xl hover:bg-blue-700 disabled:opacity-40">
            {saving ? "Wird erstellt..." : "Erstellen"}
          </button>
        </div>
      </div>
    </>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function HRTasksPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [tasks, setTasks] = useState<TaskRead[]>([]);
  const [workers, setWorkers] = useState<{ id: string; name: string; email: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [workerFilter, setWorkerFilter] = useState("");

  useEffect(() => {
    const t = auth.getAccess();
    if (!t) { router.replace("/login"); return; }
    setToken(t);
  }, [router]);

  const load = useCallback(async (t: string) => {
    setLoading(true);
    try {
      const list = await hrTasksApi.list(t);
      setTasks(list);

      // Derive unique workers
      const seen = new Set<string>();
      const ws: { id: string; name: string; email: string }[] = [];
      for (const task of list) {
        if (task.assigned_to && !seen.has(task.assigned_to)) {
          seen.add(task.assigned_to);
          ws.push({ id: task.assigned_to, name: task.assigned_to_name ?? "", email: task.assigned_to_email });
        }
      }
      setWorkers(ws);
    } catch { setTasks([]); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (token) load(token); }, [token, load]);

  async function handleCreate(body: TaskCreate) {
    if (!token) return;
    setSaving(true);
    try {
      const task = await hrTasksApi.create(token, body);
      setTasks((prev) => [task, ...prev]);
      setShowCreate(false);
    } catch { /* ignore */ }
    finally { setSaving(false); }
  }

  async function handleToggle(task: TaskRead) {
    if (!token) return;
    const newStatus = task.status === "done" ? "open" : "done";
    try {
      const updated = await hrTasksApi.update(token, task.id, { status: newStatus });
      setTasks((prev) => prev.map((t) => t.id === updated.id ? updated : t));
    } catch { /* ignore */ }
  }

  async function handleDelete(task: TaskRead) {
    if (!token || !confirm(`"${task.title}" löschen?`)) return;
    try {
      await hrTasksApi.delete(token, task.id);
      setTasks((prev) => prev.filter((t) => t.id !== task.id));
    } catch { /* ignore */ }
  }

  const filtered = tasks.filter((t) => {
    if (statusFilter && t.status !== statusFilter) return false;
    if (workerFilter && t.assigned_to !== workerFilter) return false;
    if (search && !t.title.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const openCount = tasks.filter((t) => t.status !== "done" && t.status !== "cancelled").length;
  const overdueCount = tasks.filter((t) => isOverdue(t.due_date, t.status)).length;

  return (
    <div className="min-h-screen bg-gray-50 p-4 md:p-6">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Aufgaben</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              {openCount} offen
              {overdueCount > 0 && <span className="text-red-600 font-medium"> · {overdueCount} überfällig</span>}
            </p>
          </div>
          <button onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-xl hover:bg-blue-700">
            <Plus className="w-4 h-4" /> Aufgabe
          </button>
        </div>

        {/* Filters */}
        <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 flex flex-wrap items-center gap-3 mb-5">
          <div className="relative flex-1 min-w-[160px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Aufgabe suchen..."
              className="w-full pl-8 pr-3 py-2 text-sm border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
            className="border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">Alle Status</option>
            {Object.entries(STATUS_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
          </select>
          {workers.length > 0 && (
            <select value={workerFilter} onChange={(e) => setWorkerFilter(e.target.value)}
              className="border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="">Alle Mitarbeiter</option>
              {workers.map((w) => <option key={w.id} value={w.id}>{w.name || w.email}</option>)}
            </select>
          )}
        </div>

        {/* Task list */}
        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Lade...</div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-gray-400 gap-2">
            <CheckSquare className="w-8 h-8 text-gray-200" />
            <p className="text-sm">Keine Aufgaben gefunden</p>
          </div>
        ) : (
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50 text-xs text-gray-500 font-medium">
                  <th className="px-4 py-2.5 w-8" />
                  <th className="px-4 py-2.5 text-left">Aufgabe</th>
                  <th className="px-4 py-2.5 text-left">Mitarbeiter</th>
                  <th className="px-4 py-2.5 text-left">Priorität</th>
                  <th className="px-4 py-2.5 text-left">Status</th>
                  <th className="px-4 py-2.5 text-left">Fälligkeit</th>
                  <th className="px-4 py-2.5 w-8" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filtered.map((task) => {
                  const p = PRIORITY_META[task.priority] ?? PRIORITY_META.medium;
                  const s = STATUS_META[task.status] ?? STATUS_META.open;
                  const overdue = isOverdue(task.due_date, task.status);
                  const isDone = task.status === "done";

                  return (
                    <tr key={task.id} className={`hover:bg-gray-50 ${isDone ? "opacity-50" : ""}`}>
                      <td className="px-4 py-3">
                        <button aria-label="Aufgabenstatus ändern" disabled={!!task.assigned_agent_id} onClick={() => handleToggle(task)} className="text-gray-300 hover:text-blue-600">
                          {isDone ? <CheckSquare className="w-4 h-4 text-green-500" /> : <Square className="w-4 h-4" />}
                        </button>
                      </td>
                      <td className="px-4 py-3">
                        <p className={`font-medium text-gray-900 ${isDone ? "line-through" : ""}`}>{task.title}</p>
                        {task.description && <p className="text-xs text-gray-400 truncate max-w-xs">{task.description}</p>}
                        {task.worker_note && <p className="text-xs text-blue-500 italic">Worker: {task.worker_note}</p>}
                      </td>
                      <td className="px-4 py-3 text-gray-600 text-xs">
                        {task.assigned_to_name ?? task.assigned_to_email}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${p.badge}`}>
                          {p.label}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${s.color}`}>
                          {s.label}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        {task.due_date ? (
                          <span className={`text-xs flex items-center gap-1 ${overdue ? "text-red-600 font-medium" : "text-gray-500"}`}>
                            {overdue && <AlertTriangle className="w-3 h-3" />}
                            {!overdue && <Clock className="w-3 h-3" />}
                            {fmtDate(task.due_date)}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-300">–</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {task.assigned_agent_id ? <Link href="/dashboard/agents" className="text-xs text-blue-700 underline">Ergebnis prüfen</Link> : <button aria-label="Aufgabe löschen" onClick={() => handleDelete(task)}
                          className="p-1.5 text-gray-300 hover:text-red-500 rounded-lg hover:bg-red-50">
                          <X className="w-3.5 h-3.5" />
                        </button>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showCreate && (
        <CreateTaskDialog
          workers={workers}
          onSave={handleCreate}
          onClose={() => setShowCreate(false)}
          saving={saving}
        />
      )}
    </div>
  );
}
