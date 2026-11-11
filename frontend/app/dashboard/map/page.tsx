"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import dynamic from "next/dynamic";
import { auth } from "@/lib/auth";
import { authApi, mapsApi } from "@/lib/api";
import type { MapAssignmentOut, MapWorkerOut } from "@/lib/api";
import { ModuleUpgradeHint } from "@/components/ui/ModuleGate";
import { fetchModules, MODULE_KEYS } from "@/lib/modules";

// Leaflet must be loaded client-side only (no SSR)
const LeafletMap = dynamic(() => import("./LeafletMap"), { ssr: false });

// ── Types ───────────────────────────────────────────────────────────────────

function haversineKm(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const R = 6371;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLng = ((lng2 - lng1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLng / 2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function assignmentColor(status: string): string {
  switch (status) {
    case "active": return "#3b82f6";
    case "incoming": return "#f97316";
    case "closed": return "#6b7280";
    default: return "#8b5cf6";
  }
}

function workerColor(status: string): string {
  if (status === "red") return "#ef4444";
  if (status === "yellow") return "#f59e0b";
  return "#10b981";
}

// ── Sidebar components ──────────────────────────────────────────────────────

function AuegBadge({ status, remaining }: { status: string; remaining: number }) {
  const cls =
    status === "red"
      ? "bg-red-100 text-red-700"
      : status === "yellow"
      ? "bg-yellow-100 text-yellow-700"
      : "bg-green-100 text-green-700";
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${cls}`}>
      AÜG {remaining.toFixed(1)} Mon.
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    active: "bg-blue-100 text-blue-700",
    incoming: "bg-orange-100 text-orange-700",
    closed: "bg-gray-100 text-gray-500",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${map[status] ?? "bg-gray-100 text-gray-500"}`}>
      {status}
    </span>
  );
}

// ── Main page ───────────────────────────────────────────────────────────────

export default function MapPage() {
  const router = useRouter();
  const [data, setData] = useState<{ assignments: MapAssignmentOut[]; workers: MapWorkerOut[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedAssignment, setSelectedAssignment] = useState<MapAssignmentOut | null>(null);
  const [selectedWorker, setSelectedWorker] = useState<MapWorkerOut | null>(null);
  const [showWorkers, setShowWorkers] = useState(true);
  const [isochroneKey, setIsochroneKey] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [modules, setModules] = useState<string[]>([]);

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) { router.push("/login"); return; }
    authApi.me(token).then((u) => {
      if (u.role !== "recruiter" && u.role !== "admin") router.push("/profile");
    }).catch(() => router.push("/login"));
    fetchModules(token).then(setModules);
  }, [router]);

  const loadData = useCallback(async () => {
    const token = auth.getAccess();
    if (!token) return;
    setLoading(true);
    try {
      const d = await mapsApi.getData(token);
      setData(d);
    } catch {
      setData({ assignments: [], workers: [] });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const nearbyWorkers = selectedAssignment
    ? (data?.workers ?? [])
        .filter((w) => w.lat != null && w.lng != null && selectedAssignment.lat != null && selectedAssignment.lng != null)
        .map((w) => ({
          worker: w,
          distKm: haversineKm(selectedAssignment.lat!, selectedAssignment.lng!, w.lat!, w.lng!),
        }))
        .sort((a, b) => a.distKm - b.distKm)
        .slice(0, 10)
    : [];

  if (modules.length > 0 && !modules.includes(MODULE_KEYS.MAP_VIEW)) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-16">
        <ModuleUpgradeHint name="Kartenansicht" category="core" />
      </div>
    );
  }

  const filteredAssignments = (data?.assignments ?? []).filter(
    (a) => statusFilter === "all" || a.status === statusFilter
  );

  return (
    <div className="flex h-[calc(100vh-56px)] overflow-hidden">
      {/* ── Sidebar ────────────────────────────────────────────────────── */}
      <aside className="w-80 shrink-0 border-r border-gray-200 bg-white flex flex-col overflow-hidden">
        <div className="border-b px-4 py-3 space-y-3">
          <h2 className="font-semibold text-gray-900 text-sm">Karte</h2>

          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Auftragsstatus</label>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="w-full text-xs rounded border border-gray-200 px-2 py-1.5"
            >
              <option value="all">Alle</option>
              <option value="incoming">Eingehend</option>
              <option value="active">Aktiv</option>
              <option value="closed">Abgeschlossen</option>
            </select>
          </div>

          <label className="flex items-center gap-2 text-xs text-gray-700 cursor-pointer">
            <input
              type="checkbox"
              checked={showWorkers}
              onChange={(e) => setShowWorkers(e.target.checked)}
              className="rounded"
            />
            Pool-Mitarbeiter anzeigen
          </label>

          <div>
            <label className="block text-xs font-medium text-gray-500 mb-1">Isochronen (Fahrtzeit)</label>
            <div className="flex flex-wrap gap-1">
              {[null, "15 min", "30 min", "45 min", "60 min"].map((v) => (
                <button
                  key={v ?? "off"}
                  onClick={() => setIsochroneKey(v)}
                  className={`rounded-full border px-2 py-0.5 text-[10px] transition-colors ${
                    isochroneKey === v
                      ? "border-blue-500 bg-blue-50 text-blue-700"
                      : "border-gray-200 text-gray-500 hover:border-gray-300"
                  }`}
                >
                  {v ?? "Aus"}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {loading && <p className="text-xs text-gray-400 text-center mt-8">Lade Kartendaten…</p>}

          {selectedAssignment && (
            <div className="space-y-3">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="font-semibold text-sm text-gray-900">{selectedAssignment.title}</p>
                  <p className="text-xs text-gray-500">{selectedAssignment.location ?? "–"}</p>
                </div>
                <StatusBadge status={selectedAssignment.status} />
              </div>
              {selectedAssignment.required_skills.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {selectedAssignment.required_skills.map((s) => (
                    <span key={s} className="bg-gray-100 text-gray-600 rounded-full px-2 py-0.5 text-[10px]">{s}</span>
                  ))}
                </div>
              )}
              <p className="text-xs text-gray-500">{selectedAssignment.worker_count} aktive Mitarbeiter im Einsatz</p>
              {nearbyWorkers.length > 0 && (
                <>
                  <p className="text-[11px] font-medium text-gray-500 uppercase tracking-wide mt-2">
                    Nächste Pool-Mitarbeiter
                  </p>
                  {nearbyWorkers.map(({ worker, distKm }) => (
                    <div
                      key={worker.user_id}
                      className="flex items-center gap-2 rounded-lg border border-gray-100 bg-gray-50 px-3 py-2 cursor-pointer hover:bg-gray-100 transition-colors"
                      onClick={() => setSelectedWorker(worker)}
                    >
                      <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: workerColor(worker.aueg_status) }} />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-gray-800 truncate">{worker.full_name ?? "–"}</p>
                        <p className="text-[10px] text-gray-400">{worker.preferred_location ?? "–"}</p>
                      </div>
                      <div className="text-right shrink-0">
                        <p className="text-[10px] text-gray-500">{distKm.toFixed(0)} km</p>
                        <AuegBadge status={worker.aueg_status} remaining={worker.aueg_remaining_months} />
                      </div>
                    </div>
                  ))}
                </>
              )}
              <button onClick={() => setSelectedAssignment(null)} className="text-[10px] text-gray-400 hover:text-gray-600">
                Auswahl aufheben
              </button>
            </div>
          )}

          {selectedWorker && !selectedAssignment && (
            <div className="space-y-2">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="font-semibold text-sm text-gray-900">{selectedWorker.full_name ?? "–"}</p>
                  <p className="text-xs text-gray-500">{selectedWorker.preferred_location ?? "–"}</p>
                </div>
                <AuegBadge status={selectedWorker.aueg_status} remaining={selectedWorker.aueg_remaining_months} />
              </div>
              {selectedWorker.current_assignment_title && (
                <p className="text-xs text-blue-600">Einsatz: {selectedWorker.current_assignment_title}</p>
              )}
              {!selectedWorker.current_assignment_id && (
                <p className="text-xs text-blue-600">Verfügbar</p>
              )}
              <button onClick={() => setSelectedWorker(null)} className="text-[10px] text-gray-400 hover:text-gray-600">
                Auswahl aufheben
              </button>
            </div>
          )}

          {!selectedAssignment && !selectedWorker && !loading && data && (
            <div className="space-y-1">
              <p className="text-[11px] font-medium text-gray-400 uppercase tracking-wide mb-2">
                {data.assignments.length} Aufträge · {data.workers.length} Mitarbeiter im Pool
              </p>
              {filteredAssignments.map((a) => (
                <div
                  key={a.id}
                  onClick={() => setSelectedAssignment(a)}
                  className="flex items-center gap-2 rounded-lg border border-gray-100 px-3 py-2 cursor-pointer hover:bg-gray-50 transition-colors"
                >
                  <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: assignmentColor(a.status) }} />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-gray-800 truncate">{a.title}</p>
                    <p className="text-[10px] text-gray-400">{a.location ?? "–"}</p>
                  </div>
                  <span className="text-[10px] text-gray-400">{a.worker_count} MA</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </aside>

      {/* ── Map area ──────────────────────────────────────────────────── */}
      <div className="flex-1 relative">
        {!loading && data && (
          <LeafletMap
            assignments={filteredAssignments}
            workers={showWorkers ? (data.workers ?? []) : []}
            isochroneKey={isochroneKey}
            onSelectAssignment={(a) => { setSelectedAssignment(a); setSelectedWorker(null); }}
            onSelectWorker={(w) => { setSelectedWorker(w); setSelectedAssignment(null); }}
          />
        )}
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center bg-gray-50">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
          </div>
        )}

        {/* Legend */}
        <div className="absolute top-3 right-3 z-[1000] bg-white/95 border border-gray-200 rounded-lg shadow-sm px-3 py-2 text-[10px] space-y-1">
          <p className="font-medium text-gray-600 text-[11px] mb-1.5">Legende</p>
          <div className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-blue-500 shrink-0" /><span className="text-gray-600">Aktiver Auftrag</span></div>
          <div className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-orange-500 shrink-0" /><span className="text-gray-600">Eingehender Auftrag</span></div>
          <div className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-blue-500 shrink-0" /><span className="text-gray-600">Mitarbeiter (OK)</span></div>
          <div className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-yellow-500 shrink-0" /><span className="text-gray-600">Mitarbeiter (AÜG 15 Mon.)</span></div>
          <div className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full bg-red-500 shrink-0" /><span className="text-gray-600">Mitarbeiter (AÜG krit.)</span></div>
        </div>
      </div>
    </div>
  );
}
