"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { adminApi, type AdminStats, type CustomerRead } from "@/lib/api";

const TYPE_LABELS: Record<string, string> = {
  zeitarbeit: "Zeitarbeit",
  internal_hr: "Interne HR-Abteilung",
  recruiter_agency: "Recruiter-Agentur",
  solo_recruiter: "Solo-Recruiter",
};

const PLAN_COLORS: Record<string, string> = {
  free: "bg-gray-100 text-gray-700",
  starter: "bg-blue-100 text-blue-700",
  professional: "bg-purple-100 text-purple-700",
  enterprise: "bg-amber-100 text-amber-700",
};

const STATUS_COLORS: Record<string, string> = {
  trial: "bg-yellow-100 text-yellow-700",
  active: "bg-green-100 text-green-700",
  suspended: "bg-orange-100 text-orange-700",
  churned: "bg-red-100 text-red-700",
};

function KpiCard({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <p className="text-sm text-gray-500">{label}</p>
      <p className="text-3xl font-bold text-gray-900 mt-1">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

export default function AdminHubPage() {
  const router = useRouter();
  const [stats, setStats] = useState<AdminStats | null>(null);
  const [customers, setCustomers] = useState<CustomerRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>("");

  useEffect(() => {
    const token = auth.getToken();
    const user = auth.getUser();
    if (!token || user?.role !== "admin") {
      router.replace("/dashboard");
      return;
    }
    Promise.allSettled([
      adminApi.getStats(token),
      adminApi.listCustomers(token),
    ])
      .then(([s, c]) => {
        const messages: string[] = [];
        if (s.status === "fulfilled") setStats(s.value);
        else messages.push("Kennzahlen konnten nicht geladen werden.");
        if (c.status === "fulfilled") setCustomers(c.value);
        else messages.push("Kunden konnten nicht geladen werden.");
        setError(messages.length ? messages.join(" ") : null);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [router]);

  const filtered = statusFilter
    ? customers.filter((c) => c.status === statusFilter)
    : customers;

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50">

        <div className="flex items-center justify-center h-96">
          <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full" />
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">

      <div className="max-w-7xl mx-auto px-4 py-8">
        {/* Header */}
        <div className="flex flex-wrap gap-4 items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Admin Hub</h1>
            <p className="text-sm text-gray-500 mt-1">Kunden- & Plattformverwaltung</p>
          </div>
          <div className="flex items-center gap-2">
            <Link
              href="/admin/import-runs"
              className="border border-gray-200 text-gray-700 hover:bg-gray-50 text-sm font-medium px-4 py-2 rounded-lg transition-colors"
            >
              Job-Import
            </Link>
            <Link
              href="/admin/customers/new"
              className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
            >
              + Neuer Kunde
            </Link>
          </div>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 mb-6 text-red-700 text-sm">
            {error}
          </div>
        )}

        {/* KPI Strip */}
        {stats && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <KpiCard label="Kunden gesamt" value={stats.total_customers} />
            <KpiCard label="Aktiv" value={stats.active_customers} sub="Aktive Verträge" />
            <KpiCard label="Trial" value={stats.trial_customers} sub="Testphase" />
            <KpiCard label="Suspendiert" value={stats.suspended_customers} />
          </div>
        )}

        {/* Charts Row */}
        {stats && (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
            {/* By Type */}
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <h3 className="text-sm font-semibold text-gray-700 mb-4">Nach Typ</h3>
              {Object.entries(stats.by_type).map(([type, count]) => (
                <div key={type} className="flex items-center gap-2 mb-2">
                  <div className="flex-1">
                    <div className="flex justify-between text-xs text-gray-600 mb-1">
                      <span>{TYPE_LABELS[type] ?? type}</span>
                      <span>{count}</span>
                    </div>
                    <div className="h-2 bg-gray-100 rounded">
                      <div
                        className="h-2 bg-blue-500 rounded"
                        style={{ width: `${stats.total_customers ? (count / stats.total_customers) * 100 : 0}%` }}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* By Plan */}
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <h3 className="text-sm font-semibold text-gray-700 mb-4">Nach Plan</h3>
              {Object.entries(stats.by_plan).map(([plan, count]) => (
                <div key={plan} className="flex items-center gap-2 mb-2">
                  <div className="flex-1">
                    <div className="flex justify-between text-xs text-gray-600 mb-1">
                      <span className="capitalize">{plan}</span>
                      <span>{count}</span>
                    </div>
                    <div className="h-2 bg-gray-100 rounded">
                      <div
                        className="h-2 bg-purple-500 rounded"
                        style={{ width: `${stats.total_customers ? (count / stats.total_customers) * 100 : 0}%` }}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>

            {/* Top Modules */}
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <h3 className="text-sm font-semibold text-gray-700 mb-4">Top Module</h3>
              {stats.top_modules.slice(0, 5).map(({ module_key, count }) => (
                <div key={module_key} className="flex items-center gap-2 mb-2">
                  <div className="flex-1">
                    <div className="flex justify-between text-xs text-gray-600 mb-1">
                      <span>{module_key.replace(/_/g, " ")}</span>
                      <span>{count}</span>
                    </div>
                    <div className="h-2 bg-gray-100 rounded">
                      <div
                        className="h-2 bg-blue-500 rounded"
                        style={{ width: `${stats.total_customers ? Math.min((count / stats.total_customers) * 100, 100) : 0}%` }}
                      />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Customer Table */}
        <div className="bg-white rounded-xl border border-gray-200">
          <div className="flex flex-wrap gap-3 items-center justify-between p-4 border-b border-gray-100">
            <h2 className="font-semibold text-gray-900">Kunden ({filtered.length})</h2>
            <div className="flex flex-wrap gap-2">
              {["", "trial", "active", "suspended", "churned"].map((s) => (
                <button
                  key={s}
                  onClick={() => setStatusFilter(s)}
                  className={`text-xs px-3 py-1 rounded-full transition-colors ${
                    statusFilter === s
                      ? "bg-blue-600 text-white"
                      : "bg-gray-100 text-gray-600 hover:bg-gray-200"
                  }`}
                >
                  {s === "" ? "Alle" : s.charAt(0).toUpperCase() + s.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {filtered.length === 0 ? (
            <div className="p-12 text-center text-gray-400">
              <p className="text-lg">Keine Kunden</p>
              <Link href="/admin/customers/new" className="text-blue-600 text-sm mt-2 inline-block">
                Ersten Kunden anlegen →
              </Link>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-gray-500 border-b border-gray-100">
                    <th className="px-4 py-3 font-medium">Name</th>
                    <th className="px-4 py-3 font-medium">Typ</th>
                    <th className="px-4 py-3 font-medium">Plan</th>
                    <th className="px-4 py-3 font-medium">Status</th>
                    <th className="px-4 py-3 font-medium">User</th>
                    <th className="px-4 py-3 font-medium">Module</th>
                    <th className="px-4 py-3 font-medium">Erstellt</th>
                    <th className="px-4 py-3" />
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((c) => (
                    <tr
                      key={c.id}
                      className="border-b border-gray-50 hover:bg-gray-50 transition-colors"
                    >
                      <td className="px-4 py-3">
                        <div>
                          <p className="font-medium text-gray-900">{c.name}</p>
                          <p className="text-xs text-gray-400">{c.slug}</p>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-gray-600">
                        {TYPE_LABELS[c.type] ?? c.type}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${PLAN_COLORS[c.plan] ?? ""}`}>
                          {c.plan}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_COLORS[c.status] ?? ""}`}>
                          {c.status}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-600">{c.user_count}</td>
                      <td className="px-4 py-3 text-gray-600">{c.modules.length}</td>
                      <td className="px-4 py-3 text-gray-400 text-xs">
                        {new Date(c.created_at).toLocaleDateString("de-DE")}
                      </td>
                      <td className="px-4 py-3">
                        <Link
                          href={`/admin/customers/${c.id}`}
                          className="text-blue-600 hover:text-blue-700 text-xs font-medium"
                        >
                          Details →
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
