"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";
import { recruiterApi, type RecruiterAnalytics } from "@/lib/api";
import { ModuleUpgradeHint } from "@/components/ui/ModuleGate";
import { fetchModules, MODULE_KEYS } from "@/lib/modules";

const STATUS_ORDER = ["applied", "screening", "interview", "offer", "rejected", "withdrawn", "research"];
const STATUS_LABELS: Record<string, string> = {
  applied: "Beworben",
  screening: "Screening",
  interview: "Interview",
  offer: "Angebot",
  rejected: "Abgelehnt",
  withdrawn: "Zurückgezogen",
  research: "Recherche",
};
const STATUS_COLORS: Record<string, string> = {
  applied: "bg-blue-500",
  screening: "bg-purple-500",
  interview: "bg-yellow-500",
  offer: "bg-blue-500",
  rejected: "bg-red-400",
  withdrawn: "bg-orange-400",
  research: "bg-gray-400",
};

const DAY_OPTIONS = [
  { value: 7, label: "7 Tage" },
  { value: 14, label: "14 Tage" },
  { value: 30, label: "30 Tage" },
  { value: 60, label: "60 Tage" },
  { value: 90, label: "90 Tage" },
];

function formatShortDate(iso: string): string {
  const d = new Date(iso);
  return `${d.getDate().toString().padStart(2, "0")}.${(d.getMonth() + 1).toString().padStart(2, "0")}`;
}

function BarChart({ data }: { data: { date: string; count: number }[] }) {
  const max = Math.max(...data.map((d) => d.count), 1);
  const step = Math.max(1, Math.ceil(max / 4));

  // Show at most ~30 labels for readability
  const labelEvery = Math.max(1, Math.ceil(data.length / 30));

  return (
    <div className="space-y-2">
      <div className="flex items-end gap-px h-40 overflow-hidden">
        {data.map((d, i) => (
          <div
            key={d.date}
            className="flex-1 flex flex-col justify-end group relative"
            title={`${d.date}: ${d.count}`}
          >
            <div
              className="bg-blue-500 rounded-t-sm min-h-[2px] transition-all group-hover:bg-blue-600"
              style={{ height: `${Math.max((d.count / max) * 100, d.count > 0 ? 4 : 2)}%` }}
            />
            {/* Tooltip */}
            {d.count > 0 && (
              <div className="absolute bottom-full mb-1 left-1/2 -translate-x-1/2 hidden group-hover:block bg-gray-800 text-white text-[10px] px-1.5 py-0.5 rounded whitespace-nowrap z-10">
                {d.count}
              </div>
            )}
          </div>
        ))}
      </div>
      {/* X-axis labels */}
      <div className="flex gap-px overflow-hidden">
        {data.map((d, i) => (
          <div key={d.date} className="flex-1 text-center">
            {i % labelEvery === 0 && (
              <span className="text-[9px] text-gray-400">{formatShortDate(d.date)}</span>
            )}
          </div>
        ))}
      </div>
      {/* Y-axis reference */}
      <div className="flex items-center gap-4 text-[10px] text-gray-400 justify-end">
        {[step, step * 2, step * 3, max].filter((v, i, a) => a.indexOf(v) === i && v > 0).map((v) => (
          <span key={v}>{v}</span>
        ))}
      </div>
    </div>
  );
}

export default function AnalyticsPage() {
  const router = useRouter();
  const [data, setData] = useState<RecruiterAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(30);
  const [modules, setModules] = useState<string[] | null>(null);

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) { router.push("/login"); return; }
    fetchModules(token).then(setModules).catch(() => setModules([]));
  }, [router]);

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) return;
    recruiterApi
      .getAnalytics(token, days)
      .then(setData)
      .catch(() => setError("Analytics konnten nicht geladen werden."))
      .finally(() => setLoading(false));
  }, [days]);

  if (modules !== null && !modules.includes(MODULE_KEYS.ANALYTICS_ADVANCED)) {
    return (
      <>

        <div className="max-w-2xl mx-auto px-4 py-16">
          <ModuleUpgradeHint name="Analytics (Erweitert)" category="analytics" />
        </div>
      </>
    );
  }

  const totalApps = data ? Object.values(data.funnel).reduce((a, b) => a + b, 0) : 0;
  const conversionToInterview =
    data && (data.funnel.applied ?? 0) > 0
      ? Math.round(((data.funnel.interview ?? 0) / (data.funnel.applied ?? 1)) * 100)
      : null;
  const conversionToOffer =
    data && (data.funnel.interview ?? 0) > 0
      ? Math.round(((data.funnel.offer ?? 0) / (data.funnel.interview ?? 1)) * 100)
      : null;

  return (
    <div className="min-h-screen bg-gray-50">

      <main className="mx-auto max-w-5xl px-4 py-8 space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Analytics</h1>
            <p className="mt-1 text-sm text-gray-500">Recruiting-Kennzahlen & Trends</p>
          </div>
          <select
            value={days}
            onChange={(e) => { setLoading(true); setError(null); setDays(Number(e.target.value)); }}
            className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {DAY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-24">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
          </div>
        ) : error ? (
          <div className="py-16 text-center text-sm text-red-500">{error}</div>
        ) : data ? (
          <>
            {/* KPI strip */}
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Gesamt</p>
                <p className="text-3xl font-bold text-gray-900 mt-1">{totalApps}</p>
                <p className="text-xs text-gray-400 mt-0.5">Bewerbungen</p>
              </div>
              <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Interviews</p>
                <p className="text-3xl font-bold text-purple-600 mt-1">{data.funnel.interview ?? 0}</p>
                {conversionToInterview !== null && (
                  <p className="text-xs text-gray-400 mt-0.5">{conversionToInterview}% von Beworben</p>
                )}
              </div>
              <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Angebote</p>
                <p className="text-3xl font-bold text-blue-600 mt-1">{data.funnel.offer ?? 0}</p>
                {conversionToOffer !== null && (
                  <p className="text-xs text-gray-400 mt-0.5">{conversionToOffer}% von Interview</p>
                )}
              </div>
              <div className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Abgelehnt</p>
                <p className="text-3xl font-bold text-red-500 mt-1">{data.funnel.rejected ?? 0}</p>
                <p className="text-xs text-gray-400 mt-0.5">Bewerbungen</p>
              </div>
            </div>

            {/* Daily applications chart */}
            <div className="rounded-2xl border border-gray-200 bg-white shadow-sm p-5">
              <h2 className="text-sm font-semibold text-gray-700 mb-4">
                Bewerbungen pro Tag – letzte {data.days} Tage
              </h2>
              {data.daily_applications.every((d) => d.count === 0) ? (
                <p className="text-sm text-gray-400 text-center py-10">
                  Keine Bewerbungen in diesem Zeitraum.
                </p>
              ) : (
                <BarChart data={data.daily_applications} />
              )}
            </div>

            {/* Funnel + Top Jobs side by side */}
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {/* Stage funnel */}
              <div className="rounded-2xl border border-gray-200 bg-white shadow-sm p-5">
                <h2 className="text-sm font-semibold text-gray-700 mb-4">Bewerbungs-Funnel</h2>
                {totalApps === 0 ? (
                  <p className="text-sm text-gray-400">Keine Daten.</p>
                ) : (
                  <div className="space-y-2.5">
                    {STATUS_ORDER.filter((s) => (data.funnel[s] ?? 0) > 0).map((s) => {
                      const cnt = data.funnel[s] ?? 0;
                      const pct = Math.round((cnt / totalApps) * 100);
                      return (
                        <div key={s}>
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-xs text-gray-600">{STATUS_LABELS[s] ?? s}</span>
                            <span className="text-xs font-medium text-gray-700">{cnt} ({pct}%)</span>
                          </div>
                          <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
                            <div
                              className={`h-full rounded-full ${STATUS_COLORS[s] ?? "bg-gray-400"} transition-all`}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Top jobs */}
              <div className="rounded-2xl border border-gray-200 bg-white shadow-sm p-5">
                <h2 className="text-sm font-semibold text-gray-700 mb-4">Top Inserate nach Bewerbungen</h2>
                {data.top_jobs.length === 0 ? (
                  <p className="text-sm text-gray-400">Keine Daten.</p>
                ) : (
                  <div className="space-y-2.5">
                    {data.top_jobs.map((j) => {
                      const maxCount = data.top_jobs[0]?.count ?? 1;
                      const pct = Math.round((j.count / maxCount) * 100);
                      return (
                        <div key={j.job_id}>
                          <div className="flex items-center justify-between mb-1">
                            <span className="text-xs text-gray-600 truncate max-w-[180px]" title={j.title}>
                              {j.title}
                            </span>
                            <span className="text-xs font-medium text-gray-700 shrink-0 ml-2">{j.count}</span>
                          </div>
                          <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
                            <div
                              className="h-full rounded-full bg-blue-400 transition-all"
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          </>
        ) : null}
      </main>
    </div>
  );
}
