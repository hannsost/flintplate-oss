"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { CheckSquare, Square, Clock, AlertTriangle, ChevronDown } from "lucide-react";
import { auth } from "@/lib/auth";
import { workerTasksApi, TaskRead } from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

const PRIORITY_META: Record<string, { label: string; color: string; dot: string }> = {
  low:    { label: "Niedrig",  color: "text-gray-500",  dot: "bg-gray-400" },
  medium: { label: "Mittel",   color: "text-blue-600",  dot: "bg-blue-500" },
  high:   { label: "Hoch",     color: "text-amber-600", dot: "bg-amber-500" },
  urgent: { label: "Dringend", color: "text-red-600",   dot: "bg-red-500" },
};

function fmtDate(iso: string) {
  return new Date(iso + "T00:00:00").toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function isOverdue(dueDate: string | null, status: string): boolean {
  if (!dueDate || status === "done" || status === "cancelled") return false;
  return new Date(dueDate + "T23:59:59") < new Date();
}

function isDueSoon(dueDate: string | null, status: string): boolean {
  if (!dueDate || status === "done" || status === "cancelled") return false;
  const diff = new Date(dueDate + "T23:59:59").getTime() - Date.now();
  return diff > 0 && diff < 3 * 24 * 60 * 60 * 1000;
}

// ── Task Card ─────────────────────────────────────────────────────────────────

function TaskCard({
  task,
  onToggle,
  saving,
}: {
  task: TaskRead;
  onToggle: (task: TaskRead) => void;
  saving: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const [note, setNote] = useState(task.worker_note ?? "");
  const isDone = task.status === "done";
  const overdue = isOverdue(task.due_date, task.status);
  const dueSoon = isDueSoon(task.due_date, task.status);
  const p = PRIORITY_META[task.priority] ?? PRIORITY_META.medium;

  return (
    <div className={`bg-white border rounded-xl overflow-hidden ${
      overdue ? "border-red-200" : isDone ? "border-gray-200 opacity-60" : "border-gray-200"
    }`}>
      <div className="p-4">
        <div className="flex items-start gap-3">
          <button
            onClick={() => onToggle(task)}
            disabled={saving || task.status === "cancelled"}
            className="flex-shrink-0 mt-0.5 text-gray-300 hover:text-blue-600 disabled:opacity-40 transition-colors"
          >
            {isDone
              ? <CheckSquare className="w-5 h-5 text-green-500" />
              : <Square className="w-5 h-5" />
            }
          </button>

          <div className="flex-1 min-w-0">
            <div className="flex items-start justify-between gap-2">
              <p className={`text-sm font-medium ${isDone ? "line-through text-gray-400" : "text-gray-900"}`}>
                {task.title}
              </p>
              <div className="flex items-center gap-1.5 flex-shrink-0">
                <span className={`w-1.5 h-1.5 rounded-full ${p.dot}`} />
                <span className={`text-xs font-medium ${p.color}`}>{p.label}</span>
              </div>
            </div>

            {task.due_date && (
              <p className={`text-xs mt-0.5 flex items-center gap-1 ${
                overdue ? "text-red-600 font-medium" : dueSoon ? "text-amber-600" : "text-gray-400"
              }`}>
                {overdue && <AlertTriangle className="w-3 h-3" />}
                {dueSoon && !overdue && <Clock className="w-3 h-3" />}
                Fällig: {fmtDate(task.due_date)}
                {overdue && " – Überfällig"}
              </p>
            )}

            {task.assigned_by_name && (
              <p className="text-xs text-gray-400 mt-0.5">Von {task.assigned_by_name}</p>
            )}
          </div>
        </div>

        {(task.description || task.worker_note) && (
          <button
            onClick={() => setExpanded((e) => !e)}
            className="flex items-center gap-1 text-xs text-gray-400 hover:text-gray-600 mt-2 ml-8"
          >
            <ChevronDown className={`w-3 h-3 transition-transform ${expanded ? "rotate-180" : ""}`} />
            {expanded ? "Weniger" : "Details"}
          </button>
        )}
      </div>

      {expanded && (
        <div className="border-t border-gray-100 px-4 pb-4 pt-3 ml-8 space-y-2">
          {task.description && (
            <p className="text-sm text-gray-600">{task.description}</p>
          )}
          {task.worker_note && (
            <p className="text-xs text-gray-400 italic">&quot;{task.worker_note}&quot;</p>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function WorkerTasksPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [tasks, setTasks] = useState<TaskRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showDone, setShowDone] = useState(false);

  useEffect(() => {
    const t = auth.getAccess();
    if (!t) { router.replace("/login"); return; }
    setToken(t);
  }, [router]);

  const load = useCallback(async (t: string) => {
    setLoading(true);
    try {
      const list = await workerTasksApi.list(t);
      setTasks(list);
    } catch { setTasks([]); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (token) load(token); }, [token, load]);

  async function handleToggle(task: TaskRead) {
    if (!token) return;
    const newStatus = task.status === "done" ? "open" : "done";
    setSaving(true);
    try {
      const updated = await workerTasksApi.updateStatus(token, task.id, newStatus);
      setTasks((prev) => prev.map((t) => t.id === updated.id ? updated : t));
    } catch { /* ignore */ }
    finally { setSaving(false); }
  }

  const open = tasks.filter((t) => t.status !== "done" && t.status !== "cancelled");
  const done = tasks.filter((t) => t.status === "done");
  const overdue = open.filter((t) => isOverdue(t.due_date, t.status));

  return (
    <div className="min-h-screen bg-gray-50 p-4 md:p-6">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="mb-5">
          <h1 className="text-xl font-semibold text-gray-900">Meine Aufgaben</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {open.length} offen
            {overdue.length > 0 && <span className="text-red-600 font-medium"> · {overdue.length} überfällig</span>}
          </p>
        </div>

        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Lade...</div>
        ) : (
          <>
            {open.length === 0 && done.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-40 text-gray-400 gap-2">
                <CheckSquare className="w-8 h-8 text-gray-200" />
                <p className="text-sm">Keine Aufgaben</p>
              </div>
            ) : (
              <div className="space-y-2">
                {open.map((task) => (
                  <TaskCard key={task.id} task={task} onToggle={handleToggle} saving={saving} />
                ))}

                {done.length > 0 && (
                  <>
                    <button
                      onClick={() => setShowDone((s) => !s)}
                      className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 py-2"
                    >
                      <ChevronDown className={`w-3.5 h-3.5 transition-transform ${showDone ? "rotate-180" : ""}`} />
                      {done.length} erledigte Aufgabe{done.length !== 1 ? "n" : ""}
                    </button>
                    {showDone && done.map((task) => (
                      <TaskCard key={task.id} task={task} onToggle={handleToggle} saving={saving} />
                    ))}
                  </>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
