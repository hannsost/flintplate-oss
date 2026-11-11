"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";
import { authApi, zeitarbeitApi, canvasApi } from "@/lib/api";
import type {
  AssignmentRead,
  PoolWorkerRead,
  JobCanvasRead,
  WorkerCanvasRead,
  DispositionRead,
} from "@/lib/api";
import { VermerkPanel } from "@/components/vermerke/VermerkPanel";
import { ModuleUpgradeHint } from "@/components/ui/ModuleGate";
import { fetchModules, MODULE_KEYS } from "@/lib/modules";

// ── AÜG status badge ──────────────────────────────────────────────────────────
function AuegBadge({ status, remaining }: { status: string; remaining: number }) {
  const cls =
    status === "red"
      ? "bg-red-100 text-red-700 border-red-200"
      : status === "yellow"
      ? "bg-yellow-100 text-yellow-700 border-yellow-200"
      : "bg-green-100 text-green-700 border-green-200";
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${cls}`}>
      AÜG {remaining.toFixed(1)} Mon.
    </span>
  );
}

// ── Score ring ────────────────────────────────────────────────────────────────
function ScoreRing({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = pct >= 80 ? "text-green-600 border-green-500" : pct >= 60 ? "text-yellow-600 border-yellow-500" : "text-gray-400 border-gray-300";
  return (
    <div className={`flex items-center justify-center w-10 h-10 rounded-full border-2 font-bold text-sm shrink-0 ${color}`}>
      {pct}
    </div>
  );
}

// ── Pool worker card (draggable) ──────────────────────────────────────────────
function PoolCard({
  worker,
  onDragStart,
  onClick,
  selected,
}: {
  worker: PoolWorkerRead;
  onDragStart: (w: PoolWorkerRead) => void;
  onClick: (w: PoolWorkerRead) => void;
  selected: boolean;
}) {
  return (
    <div
      draggable
      onDragStart={() => onDragStart(worker)}
      onClick={() => onClick(worker)}
      className={`cursor-pointer rounded-lg border p-3 transition-all hover:shadow-sm select-none ${
        selected ? "border-blue-400 bg-blue-50" : "border-gray-200 bg-white hover:border-gray-300"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-gray-900 truncate">
            {worker.full_name ?? "Anonym"}
          </p>
          {worker.headline && (
            <p className="text-xs text-gray-500 truncate mt-0.5">{worker.headline}</p>
          )}
          {worker.location && (
            <p className="text-[10px] text-gray-400 mt-0.5">{worker.location}</p>
          )}
        </div>
        <AuegBadge status={worker.aueg_status} remaining={Number(worker.aueg_remaining_months)} />
      </div>
      {worker.skills.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {worker.skills.slice(0, 4).map((s) => (
            <span key={s} className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] text-gray-600">
              {s}
            </span>
          ))}
          {worker.skills.length > 4 && (
            <span className="text-[10px] text-gray-400">+{worker.skills.length - 4}</span>
          )}
        </div>
      )}
    </div>
  );
}

// ── Disposition card (drop target) ────────────────────────────────────────────
function DispositionCard({ disp, onDrop }: { disp: DispositionRead; onDrop: () => void }) {
  const [over, setOver] = useState(false);
  const statusColor =
    disp.status === "confirmed" || disp.status === "active"
      ? "border-green-300 bg-green-50"
      : disp.status === "suggested"
      ? "border-blue-200 bg-blue-50"
      : "border-gray-200 bg-gray-50";

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={() => { setOver(false); onDrop(); }}
      className={`rounded-lg border-2 p-3 transition-all ${statusColor} ${over ? "scale-[1.02] shadow-md" : ""}`}
    >
      <div className="flex items-center gap-3">
        <ScoreRing score={Number(disp.score)} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-gray-900">{disp.worker_name ?? "Kandidat"}</p>
          {disp.worker_headline && (
            <p className="text-xs text-gray-500 truncate">{disp.worker_headline}</p>
          )}
          <div className="flex flex-wrap gap-1 mt-1">
            {disp.matched_skills.slice(0, 4).map((s) => (
              <span key={s} className="rounded-full bg-green-100 px-2 py-0.5 text-[10px] text-green-700">{s}</span>
            ))}
            {disp.missing_skills.slice(0, 2).map((s) => (
              <span key={s} className="rounded-full bg-red-50 px-2 py-0.5 text-[10px] text-red-500">{s}</span>
            ))}
          </div>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
          disp.status === "confirmed" ? "bg-green-200 text-green-800" : "bg-blue-100 text-blue-700"
        }`}>
          {disp.status}
        </span>
      </div>
      <div className="mt-2">
        <VermerkPanel targetType="candidate" targetId={disp.worker_id} compact />
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function CanvasPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"job" | "worker">("job");
  const [assignments, setAssignments] = useState<AssignmentRead[]>([]);
  const [poolWorkers, setPoolWorkers] = useState<PoolWorkerRead[]>([]);
  const [selectedAssignment, setSelectedAssignment] = useState<AssignmentRead | null>(null);
  const [selectedWorker, setSelectedWorker] = useState<PoolWorkerRead | null>(null);
  const [jobCanvas, setJobCanvas] = useState<JobCanvasRead | null>(null);
  const [workerCanvas, setWorkerCanvas] = useState<WorkerCanvasRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [modules, setModules] = useState<string[] | null>(null);

  const dragWorker = useRef<PoolWorkerRead | null>(null);

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) { router.push("/login"); return; }
    authApi.me(token).then((u) => {
      if (u.role !== "recruiter" && u.role !== "admin") router.push("/profile");
    }).catch(() => router.push("/login"));
    fetchModules(token).then(setModules).catch(() => setModules([]));
  }, [router]);

  // Load assignments + pool workers
  useEffect(() => {
    const token = auth.getAccess();
    if (!token) return;
    setLoading(true);
    Promise.all([
      zeitarbeitApi.listAssignments(token),
      canvasApi.getPool(token),
    ]).then(([ass, pool]) => {
      setAssignments(ass);
      setPoolWorkers(pool);
    }).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (modules !== null && !modules.includes(MODULE_KEYS.KANBAN_PIPELINE)) {
    return (
      <>

        <div className="max-w-2xl mx-auto px-4 py-16">
          <ModuleUpgradeHint name="Kanban Pipeline / Canvas" category="core" />
        </div>
      </>
    );
  }

  // Load job-first detail
  async function selectAssignment(a: AssignmentRead) {
    setSelectedAssignment(a);
    setJobCanvas(null);
    const token = auth.getAccess();
    if (!token) return;
    setDetailLoading(true);
    try {
      const canvas = await canvasApi.getJobView(token, a.id);
      setJobCanvas(canvas);
    } finally {
      setDetailLoading(false);
    }
  }

  // Load worker-first detail
  async function selectWorker(w: PoolWorkerRead) {
    setSelectedWorker(w);
    setWorkerCanvas(null);
    const token = auth.getAccess();
    if (!token) return;
    setDetailLoading(true);
    try {
      const canvas = await canvasApi.getWorkerView(token, w.user_id);
      setWorkerCanvas(canvas);
    } finally {
      setDetailLoading(false);
    }
  }

  // Drag-drop assign
  async function handleDrop(assignmentId: string) {
    const worker = dragWorker.current;
    if (!worker) return;
    const token = auth.getAccess();
    if (!token) return;
    try {
      await canvasApi.assign(token, { assignment_id: assignmentId, worker_id: worker.user_id });
      // Reload job canvas
      if (selectedAssignment) await selectAssignment(selectedAssignment);
    } catch {
      alert("Zuweisung fehlgeschlagen.");
    }
  }

  if (loading) {
    return (
      <>

        <div className="flex min-h-[60vh] items-center justify-center">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      </>
    );
  }

  const openAssignments = assignments.filter((a) => ["incoming", "matching"].includes(a.status));
  const activeAssignments = assignments.filter((a) => a.status === "active");

  return (
    <>

      <main className="mx-auto max-w-7xl px-4 py-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-xl font-bold text-gray-900">Workforce Canvas</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              {poolWorkers.length} Worker im Pool · {openAssignments.length} offene Aufträge
            </p>
          </div>
          {/* Mode toggle */}
          <div className="flex rounded-lg border border-gray-200 overflow-hidden">
            <button
              onClick={() => setMode("job")}
              className={`px-4 py-2 text-sm font-medium transition-colors ${
                mode === "job" ? "bg-blue-600 text-white" : "bg-white text-gray-600 hover:bg-gray-50"
              }`}
            >
              Job-first
            </button>
            <button
              onClick={() => setMode("worker")}
              className={`px-4 py-2 text-sm font-medium transition-colors border-l border-gray-200 ${
                mode === "worker" ? "bg-blue-600 text-white" : "bg-white text-gray-600 hover:bg-gray-50"
              }`}
            >
              Worker-first
            </button>
          </div>
        </div>

        {/* ── JOB-FIRST VIEW ─────────────────────────────────────────── */}
        {mode === "job" && (
          <div className="grid grid-cols-12 gap-4 h-[calc(100vh-180px)]">
            {/* Left: Assignment list */}
            <div className="col-span-3 overflow-y-auto space-y-2 pr-1">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Offene Aufträge</p>
              {openAssignments.length === 0 && (
                <p className="text-sm text-gray-400 italic">Keine offenen Aufträge.</p>
              )}
              {openAssignments.map((a) => (
                <button
                  key={a.id}
                  onClick={() => selectAssignment(a)}
                  className={`w-full text-left rounded-lg border p-3 transition-all hover:shadow-sm ${
                    selectedAssignment?.id === a.id
                      ? "border-blue-400 bg-blue-50"
                      : "border-gray-200 bg-white hover:border-gray-300"
                  }`}
                >
                  <p className="text-sm font-semibold text-gray-900 truncate">{a.title}</p>
                  {a.location && <p className="text-xs text-gray-400 mt-0.5">{a.location}</p>}
                  <div className="flex gap-1 mt-1 flex-wrap">
                    {(a.required_skills ?? []).slice(0, 3).map((s) => (
                      <span key={s} className="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] text-gray-600">{s}</span>
                    ))}
                  </div>
                </button>
              ))}

              {activeAssignments.length > 0 && (
                <>
                  <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mt-4 mb-2">Aktiv</p>
                  {activeAssignments.map((a) => (
                    <button
                      key={a.id}
                      onClick={() => selectAssignment(a)}
                      className={`w-full text-left rounded-lg border p-3 transition-all opacity-70 hover:opacity-100 ${
                        selectedAssignment?.id === a.id
                          ? "border-blue-400 bg-blue-50"
                          : "border-green-200 bg-green-50"
                      }`}
                    >
                      <p className="text-sm font-semibold text-gray-900 truncate">{a.title}</p>
                    </button>
                  ))}
                </>
              )}
            </div>

            {/* Center: Disposition cards / drop zone */}
            <div className="col-span-6 overflow-y-auto pr-1">
              {!selectedAssignment && (
                <div className="flex h-full items-center justify-center text-gray-400 text-sm">
                  Auftrag links auswählen
                </div>
              )}
              {selectedAssignment && (
                <>
                  <div className="mb-4">
                    <h2 className="font-semibold text-gray-900">{selectedAssignment.title}</h2>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {selectedAssignment.location ?? "Kein Standort"} ·{" "}
                      {selectedAssignment.shift ?? "Schicht offen"}
                    </p>
                    {/* Drop zone when no dispositions yet */}
                    <div
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={() => handleDrop(selectedAssignment.id)}
                      className="mt-3 rounded-lg border-2 border-dashed border-blue-300 bg-blue-50/50 p-3 text-center text-xs text-blue-600"
                    >
                      Worker hier ablegen zum Zuweisen
                    </div>
                  </div>
                  {detailLoading && (
                    <div className="flex justify-center py-8">
                      <div className="h-5 w-5 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
                    </div>
                  )}
                  {jobCanvas && !detailLoading && (
                    <div className="space-y-2">
                      {jobCanvas.dispositions.length === 0 && (
                        <p className="text-sm text-gray-400 italic text-center py-6">
                          Noch keine Kandidaten. Matching starten oder Worker aus dem Pool ziehen.
                        </p>
                      )}
                      {jobCanvas.dispositions.map((d) => (
                        <DispositionCard
                          key={d.id}
                          disp={d}
                          onDrop={() => handleDrop(selectedAssignment.id)}
                        />
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Right: Pool workers (draggable) */}
            <div className="col-span-3 overflow-y-auto pl-1 border-l border-gray-100">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
                Pool ({poolWorkers.length})
              </p>
              {poolWorkers.length === 0 && (
                <p className="text-sm text-gray-400 italic">Keine Worker im Pool.</p>
              )}
              <div className="space-y-2">
                {poolWorkers.map((w) => (
                  <PoolCard
                    key={w.user_id}
                    worker={w}
                    selected={false}
                    onDragStart={(worker) => { dragWorker.current = worker; }}
                    onClick={() => {}}
                  />
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ── WORKER-FIRST VIEW ───────────────────────────────────────── */}
        {mode === "worker" && (
          <div className="grid grid-cols-12 gap-4 h-[calc(100vh-180px)]">
            {/* Left: Pool worker list */}
            <div className="col-span-4 overflow-y-auto space-y-2 pr-1">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Worker-Pool</p>
              {poolWorkers.length === 0 && (
                <p className="text-sm text-gray-400 italic">Keine Worker im Pool.</p>
              )}
              {poolWorkers.map((w) => (
                <PoolCard
                  key={w.user_id}
                  worker={w}
                  selected={selectedWorker?.user_id === w.user_id}
                  onDragStart={() => {}}
                  onClick={selectWorker}
                />
              ))}
            </div>

            {/* Right: Worker detail */}
            <div className="col-span-8 overflow-y-auto pl-1 border-l border-gray-100">
              {!selectedWorker && (
                <div className="flex h-full items-center justify-center text-gray-400 text-sm">
                  Worker links auswählen
                </div>
              )}
              {selectedWorker && (
                <>
                  <div className="mb-4 flex items-start justify-between">
                    <div>
                      <h2 className="font-semibold text-gray-900">{selectedWorker.full_name ?? "Anonym"}</h2>
                      {selectedWorker.headline && (
                        <p className="text-xs text-gray-500 mt-0.5">{selectedWorker.headline}</p>
                      )}
                      <div className="flex items-center gap-2 mt-1">
                        <AuegBadge
                          status={selectedWorker.aueg_status}
                          remaining={Number(selectedWorker.aueg_remaining_months)}
                        />
                      </div>
                    </div>
                    <VermerkPanel targetType="candidate" targetId={selectedWorker.user_id} compact />
                  </div>

                  {detailLoading && (
                    <div className="flex justify-center py-8">
                      <div className="h-5 w-5 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
                    </div>
                  )}

                  {workerCanvas && !detailLoading && (
                    <div className="space-y-5">
                      {/* Active assignments */}
                      {workerCanvas.active_assignments.length > 0 && (
                        <div>
                          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
                            Aktive Einsätze
                          </p>
                          <div className="space-y-2">
                            {workerCanvas.active_assignments.map((a) => (
                              <div key={a.id} className="rounded-lg border border-green-200 bg-green-50 p-3">
                                <p className="text-sm font-semibold text-gray-900">{a.title}</p>
                                <p className="text-xs text-gray-500 mt-0.5">
                                  {a.location ?? "Kein Standort"} ·{" "}
                                  {a.start_date && new Date(a.start_date).toLocaleDateString("de-DE")}
                                  {a.end_date && ` – ${new Date(a.end_date).toLocaleDateString("de-DE")}`}
                                </p>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Recommended assignments */}
                      <div>
                        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
                          Empfohlene Aufträge
                        </p>
                        {workerCanvas.recommended_assignments.length === 0 && (
                          <p className="text-sm text-gray-400 italic">Keine offenen Aufträge verfügbar.</p>
                        )}
                        <div className="space-y-2">
                          {workerCanvas.recommended_assignments.map((a) => (
                            <div key={a.id} className="rounded-lg border border-gray-200 bg-white p-3">
                              <div className="flex items-start justify-between gap-3">
                                <div>
                                  <p className="text-sm font-semibold text-gray-900">{a.title}</p>
                                  <p className="text-xs text-gray-500 mt-0.5">
                                    {a.location ?? "Kein Standort"} · {a.shift ?? "Schicht offen"}
                                  </p>
                                  <div className="flex flex-wrap gap-1 mt-1">
                                    {(a.required_skills ?? []).slice(0, 5).map((s) => (
                                      <span
                                        key={s}
                                        className={`rounded-full px-2 py-0.5 text-[10px] ${
                                          selectedWorker.skills.includes(s)
                                            ? "bg-green-100 text-green-700"
                                            : "bg-red-50 text-red-500"
                                        }`}
                                      >
                                        {s}
                                      </span>
                                    ))}
                                  </div>
                                </div>
                                <button
                                  onClick={async () => {
                                    const token = auth.getAccess();
                                    if (!token) return;
                                    try {
                                      await canvasApi.assign(token, {
                                        assignment_id: a.id,
                                        worker_id: selectedWorker.user_id,
                                      });
                                      await selectWorker(selectedWorker);
                                    } catch {
                                      alert("Zuweisung fehlgeschlagen.");
                                    }
                                  }}
                                  className="rounded-md bg-blue-50 border border-blue-200 px-3 py-1.5 text-xs text-blue-700 hover:bg-blue-100 shrink-0"
                                >
                                  Zuweisen
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        )}
      </main>
    </>
  );
}
