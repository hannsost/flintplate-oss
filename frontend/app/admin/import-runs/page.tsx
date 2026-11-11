"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { adminApi, type ImportRun } from "@/lib/api";

const STATUS_STYLES: Record<string, string> = {
  running: "bg-yellow-100 text-yellow-700",
  done: "bg-green-100 text-green-700",
  error: "bg-red-100 text-red-700",
};

const SOURCES = [
  { value: "all", label: "Alle Quellen" },
  { value: "mock", label: "Mock (Dev)" },
  { value: "bundesagentur", label: "Bundesagentur für Arbeit" },
  { value: "stepstone_de", label: "StepStone RSS" },
  { value: "indeed_de", label: "Indeed RSS" },
  { value: "remotive", label: "Remotive RSS" },
  { value: "weworkremotely_programming", label: "WeWorkRemotely RSS" },
];

function formatDuration(started: string, finished: string | null): string {
  if (!finished) return "läuft…";
  const ms = new Date(finished).getTime() - new Date(started).getTime();
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export default function ImportRunsPage() {
  const router = useRouter();
  const [runs, setRuns] = useState<ImportRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [selectedSource, setSelectedSource] = useState("all");
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = auth.getToken();
    if (!token) return;
    try {
      const data = await adminApi.getImportRuns(token);
      setRuns(data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Fehler beim Laden.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const token = auth.getToken();
    const user = auth.getUser();
    if (!token || user?.role !== "admin") { router.replace("/dashboard"); return; }
    load();
  }, [router, load]);

  async function handleTrigger() {
    const token = auth.getToken();
    if (!token) return;
    setTriggering(true);
    setSuccessMsg(null);
    setError(null);
    try {
      await adminApi.triggerImport(token, selectedSource);
      setSuccessMsg(`Import für "${selectedSource}" gestartet. Seite in 5s neu laden…`);
      setTimeout(() => { load(); setSuccessMsg(null); }, 5000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Import-Trigger fehlgeschlagen.");
    } finally {
      setTriggering(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">

      <div className="max-w-6xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="flex items-center gap-3 mb-6">
          <Link href="/admin" className="text-gray-400 hover:text-gray-600 text-sm">← Admin Hub</Link>
          <span className="text-gray-300">/</span>
          <h1 className="text-xl font-bold text-gray-900">Job-Import</h1>
          <Link href="/admin/job-publications" className="text-sm text-blue-700 underline">Importierte Stellen zur Veröffentlichung prüfen</Link>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-4 text-red-700 text-sm">{error}</div>
        )}
        {successMsg && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-3 mb-4 text-green-700 text-sm">{successMsg}</div>
        )}

        {/* Trigger Panel */}
        <div className="bg-white rounded-xl border border-gray-200 p-5 mb-6">
          <h2 className="font-semibold text-gray-900 mb-3">Manueller Import</h2>
          <div className="flex items-center gap-3 flex-wrap">
            <select
              value={selectedSource}
              onChange={(e) => setSelectedSource(e.target.value)}
              className="rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700 bg-white min-w-[220px]"
            >
              {SOURCES.map((s) => (
                <option key={s.value} value={s.value}>{s.label}</option>
              ))}
            </select>
            <button
              onClick={handleTrigger}
              disabled={triggering}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {triggering ? "Wird gestartet…" : "Import starten"}
            </button>
            <button
              onClick={load}
              className="rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
            >
              Aktualisieren
            </button>
          </div>
          <p className="text-xs text-gray-400 mt-2">
            Automatischer Crawl läuft täglich um 03:00 Uhr (Quelle: JOB_CRAWLER_MOCK env).
          </p>
        </div>

        {/* Runs Table */}
        <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Quelle</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Status</th>
                <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase">Gefunden</th>
                <th className="px-4 py-3 text-right text-xs font-semibold text-gray-500 uppercase">Neu</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Dauer</th>
                <th className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase">Gestartet</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {loading ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-400">
                    <div className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
                  </td>
                </tr>
              ) : runs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-gray-400 text-sm">
                    Noch keine Import-Runs. Starte einen manuellen Import.
                  </td>
                </tr>
              ) : (
                runs.map((run) => (
                  <tr key={run.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium text-gray-800">{run.source}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[run.status] ?? "bg-gray-100 text-gray-600"}`}>
                        {run.status}
                      </span>
                      {run.error_msg && (
                        <p className="text-[10px] text-red-500 mt-0.5 max-w-[200px] truncate" title={run.error_msg}>
                          {run.error_msg}
                        </p>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right text-gray-700">{run.jobs_found}</td>
                    <td className="px-4 py-3 text-right font-semibold text-green-700">+{run.jobs_new}</td>
                    <td className="px-4 py-3 text-gray-500 text-xs">
                      {formatDuration(run.started_at, run.finished_at)}
                    </td>
                    <td className="px-4 py-3 text-gray-400 text-xs">
                      {new Date(run.started_at).toLocaleString("de-DE")}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
