"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";
import { zeitarbeitApi, ApiError, type AssignmentRead, type ZeitarbeitStats } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { AssignmentModal } from "@/components/zeitarbeit/AssignmentModal";
import { DispositionDrawer } from "@/components/zeitarbeit/DispositionDrawer";
import { ModuleUpgradeHint } from "@/components/ui/ModuleGate";
import { fetchModules, MODULE_KEYS } from "@/lib/modules";

// ── Status config ─────────────────────────────────────────────────────────────

const STATUSES = ["incoming", "matching", "active", "extended", "completed", "cancelled"] as const;
type AssignmentStatus = typeof STATUSES[number];

const STATUS_CONFIG: Record<AssignmentStatus, { label: string; bg: string; border: string; color: string }> = {
  incoming:  { label: "Eingang",      bg: "bg-gray-50",    border: "border-gray-200",  color: "text-gray-700"   },
  matching:  { label: "Matching",     bg: "bg-blue-50",    border: "border-blue-200",  color: "text-blue-700"   },
  active:    { label: "Im Einsatz",   bg: "bg-green-50",   border: "border-green-200", color: "text-green-700"  },
  extended:  { label: "Verlängert",   bg: "bg-teal-50",    border: "border-teal-200",  color: "text-teal-700"   },
  completed: { label: "Abgeschlossen",bg: "bg-purple-50",  border: "border-purple-200",color: "text-purple-700" },
  cancelled: { label: "Abgesagt",     bg: "bg-red-50",     border: "border-red-200",   color: "text-red-600"    },
};

// ── Assignment card ───────────────────────────────────────────────────────────

function AssignmentCard({
  a,
  onDragStart,
  onDragEnd,
  onClick,
}: {
  a: AssignmentRead;
  onDragStart: (e: React.DragEvent, a: AssignmentRead) => void;
  onDragEnd: () => void;
  onClick: (a: AssignmentRead) => void;
}) {
  return (
    <div
      draggable
      onDragStart={(e) => onDragStart(e, a)}
      onDragEnd={onDragEnd}
      onClick={() => onClick(a)}
      className="rounded-lg border border-gray-200 bg-white p-3 shadow-sm cursor-grab active:cursor-grabbing hover:shadow-md transition-shadow select-none"
    >
      <p className="font-medium text-gray-900 text-sm truncate">{a.title}</p>
      {a.location && <p className="text-xs text-gray-500 mt-0.5 truncate">📍 {a.location}</p>}
      <div className="mt-2 flex flex-wrap gap-1">
        {a.required_skills.slice(0, 4).map((s) => (
          <span key={s} className="rounded-full bg-blue-50 border border-blue-100 px-1.5 py-0.5 text-[10px] text-blue-700">
            {s}
          </span>
        ))}
        {a.required_skills.length > 4 && (
          <span className="text-[10px] text-gray-400">+{a.required_skills.length - 4}</span>
        )}
      </div>
      {a.shift && (
        <p className="mt-1.5 text-[10px] text-gray-400">
          🕐 {a.shift === "day" ? "Tagschicht" : a.shift === "night" ? "Nachtschicht" : "Flexibel"}
        </p>
      )}
      {a.hourly_rate && (
        <p className="mt-0.5 text-[10px] text-gray-500 font-medium">
          {Number(a.hourly_rate).toFixed(2)} €/h
        </p>
      )}
    </div>
  );
}

// ── Kanban column ─────────────────────────────────────────────────────────────

function KanbanCol({
  status,
  assignments,
  onDragStart,
  onDragEnd,
  onDrop,
  onCardClick,
}: {
  status: AssignmentStatus;
  assignments: AssignmentRead[];
  onDragStart: (e: React.DragEvent, a: AssignmentRead) => void;
  onDragEnd: () => void;
  onDrop: (status: AssignmentStatus) => void;
  onCardClick: (a: AssignmentRead) => void;
}) {
  const [over, setOver] = useState(false);
  const cfg = STATUS_CONFIG[status];

  return (
    <div
      className={`flex flex-col rounded-xl border transition-colors min-w-[210px] w-[210px] shrink-0 ${
        over ? "border-blue-400 bg-blue-50/40" : `border-gray-200 ${cfg.bg}`
      }`}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={() => { setOver(false); onDrop(status); }}
    >
      <div className={`px-3 py-2 border-b ${cfg.border} flex items-center justify-between`}>
        <span className={`text-xs font-semibold uppercase tracking-wide ${cfg.color}`}>{cfg.label}</span>
        <span className="text-xs bg-white border border-gray-200 rounded-full px-1.5 py-0.5 text-gray-500">
          {assignments.length}
        </span>
      </div>
      <div className="flex flex-col gap-2 p-2 flex-1 overflow-y-auto max-h-[calc(100vh-260px)]">
        {assignments.map((a) => (
          <AssignmentCard
            key={a.id}
            a={a}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            onClick={onCardClick}
          />
        ))}
        {assignments.length === 0 && (
          <p className="py-6 text-center text-xs text-gray-400">Keine Aufträge</p>
        )}
      </div>
    </div>
  );
}

// ── KPI card ──────────────────────────────────────────────────────────────────

function KpiCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium text-gray-500">{label}</p>
      <p className="text-2xl font-bold text-gray-900 mt-0.5">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function ZeitarbeitPage() {
  const router = useRouter();
  const [assignments, setAssignments] = useState<AssignmentRead[]>([]);
  const [stats, setStats] = useState<ZeitarbeitStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [selected, setSelected] = useState<AssignmentRead | null>(null);
  const [modules, setModules] = useState<string[] | null>(null);
  const dragItem = useRef<AssignmentRead | null>(null);

  useEffect(() => {
    const token = auth.getAccess();
    if (token) fetchModules(token).then(setModules).catch(() => setModules([]));
  }, []);

  const load = useCallback(async () => {
    const token = auth.getAccess();
    if (!token) { router.replace("/login"); return; }
    setLoading(true);
    try {
      const [a, s] = await Promise.all([
        zeitarbeitApi.listAssignments(token),
        zeitarbeitApi.stats(token),
      ]);
      setAssignments(a);
      setStats(s);
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => { load(); }, [load]);

  function byStatus(s: AssignmentStatus) {
    return assignments.filter((a) => a.status === s);
  }

  function handleDragStart(e: React.DragEvent, a: AssignmentRead) {
    dragItem.current = a;
    e.dataTransfer.effectAllowed = "move";
  }

  async function handleDrop(targetStatus: AssignmentStatus) {
    const a = dragItem.current;
    dragItem.current = null;
    if (!a || a.status === targetStatus) return;
    const token = auth.getAccess();
    if (!token) return;

    // Optimistic update
    setAssignments((prev) =>
      prev.map((x) => x.id === a.id ? { ...x, status: targetStatus } : x)
    );
    try {
      await zeitarbeitApi.updateAssignment(token, a.id, { status: targetStatus });
    } catch {
      load();
    }
  }

  if (modules !== null && !modules.includes(MODULE_KEYS.ZEITARBEIT_POOL)) {
    return (
      <>

        <div className="max-w-2xl mx-auto px-4 py-16">
          <ModuleUpgradeHint name="Zeitarbeiter-Pool" category="core" />
        </div>
      </>
    );
  }

  return (
    <>

      <main className="px-4 py-6 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Zeitarbeit-Aufträge</h1>
            <p className="text-sm text-gray-400 mt-0.5">Dispositions-Engine & AÜG-Compliance</p>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => router.push("/dashboard/zeitarbeit/pool")}>
              👥 Pool ({stats?.workers_in_pool ?? 0})
            </Button>
            <Button size="sm" onClick={() => setShowCreate(true)}>
              + Neuer Auftrag
            </Button>
          </div>
        </div>

        {/* KPIs */}
        {stats && (
          <div className="grid grid-cols-3 sm:grid-cols-6 gap-3">
            <KpiCard label="Aufträge" value={String(stats.total_assignments)} />
            <KpiCard label="Im Einsatz" value={String(stats.active_assignments)} />
            <KpiCard label="Pool-Mitarbeiter" value={String(stats.workers_in_pool)} />
            <KpiCard label="Dispositions" value={String(stats.total_dispositions)} />
            <KpiCard label="Aktive Dispositions" value={String(stats.active_dispositions)} />
            <KpiCard
              label="Ø Match-Score"
              value={`${Math.round(Number(stats.avg_fill_score) * 100)} %`}
              sub="Alle Dispositions"
            />
          </div>
        )}

        {/* Kanban */}
        {loading ? (
          <div className="flex justify-center py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
          </div>
        ) : (
          <div className="flex gap-3 overflow-x-auto pb-4">
            {STATUSES.map((s) => (
              <KanbanCol
                key={s}
                status={s}
                assignments={byStatus(s)}
                onDragStart={handleDragStart}
                onDragEnd={() => { dragItem.current = null; }}
                onDrop={handleDrop}
                onCardClick={setSelected}
              />
            ))}
          </div>
        )}
      </main>

      {showCreate && (
        <AssignmentModal
          onClose={() => setShowCreate(false)}
          onSaved={(a) => {
            setAssignments((prev) => [a, ...prev]);
            setShowCreate(false);
          }}
        />
      )}

      {selected && (
        <DispositionDrawer
          assignment={selected}
          onClose={() => setSelected(null)}
          onUpdated={(updated) => {
            setAssignments((prev) => prev.map((x) => x.id === updated.id ? updated : x));
            setSelected(updated);
          }}
          onDeleted={(id) => {
            setAssignments((prev) => prev.filter((x) => x.id !== id));
            setSelected(null);
          }}
        />
      )}
    </>
  );
}
