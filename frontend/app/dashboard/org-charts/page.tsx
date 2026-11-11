"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { orgChartApi, type OrgChartRead, type OrgChartType } from "@/lib/api";
import { GitBranch, LayoutGrid, Minus, Layers, Building2 } from "lucide-react";

const CHART_TYPE_LABELS: Record<OrgChartType, string> = {
  hierarchical: "Hierarchisch",
  matrix: "Matrix",
  flat: "Flach",
  divisional: "Divisional",
};

const CHART_TYPE_DESC: Record<OrgChartType, string> = {
  hierarchical: "Klassische Baumstruktur top-down",
  matrix: "Doppelte Berichtslinie (Projekt + Abteilung)",
  flat: "Egalitär, keine Hierarchie",
  divisional: "Gruppiert nach Business Unit / Region",
};

const CHART_TYPE_ICONS: Record<OrgChartType, React.ElementType> = {
  hierarchical: GitBranch,
  matrix: LayoutGrid,
  flat: Minus,
  divisional: Layers,
};

export default function OrgChartsPage() {
  const router = useRouter();
  const [charts, setCharts] = useState<OrgChartRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState<string | null>(null);

  useEffect(() => {
    const token = auth.getToken();
    if (!token) { router.replace("/login"); return; }
    orgChartApi.list(token)
      .then(setCharts)
      .finally(() => setLoading(false));
  }, [router]);

  async function handleDelete(id: string, name: string) {
    if (!confirm(`Organigramm "${name}" wirklich löschen?`)) return;
    const token = auth.getToken();
    if (!token) return;
    setDeleting(id);
    try {
      await orgChartApi.delete(token, id);
      setCharts((prev) => prev.filter((c) => c.id !== id));
    } finally {
      setDeleting(null);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">

      <div className="max-w-5xl mx-auto px-4 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Organigramme</h1>
            <p className="text-sm text-gray-500 mt-1">Visualisieren Sie Ihre Unternehmensstruktur</p>
          </div>
          <Link
            href="/dashboard/org-charts/new"
            className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold px-4 py-2 rounded-lg transition-colors"
          >
            + Neues Organigramm
          </Link>
        </div>

        {loading && (
          <div className="flex justify-center py-20">
            <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full" />
          </div>
        )}

        {!loading && charts.length === 0 && (
          <div className="text-center py-20">
            <div className="flex justify-center mb-4"><Building2 size={48} className="text-gray-300" /></div>
            <p className="text-lg font-medium text-gray-700 mb-2">Noch keine Organigramme</p>
            <p className="text-sm text-gray-400 mb-6">Erstellen Sie Ihr erstes Organigramm</p>
            <Link
              href="/dashboard/org-charts/new"
              className="bg-blue-600 hover:bg-blue-700 text-white text-sm font-semibold px-6 py-2.5 rounded-lg transition-colors"
            >
              Jetzt erstellen
            </Link>
          </div>
        )}

        {!loading && charts.length > 0 && (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {charts.map((chart) => (
              <div
                key={chart.id}
                className="bg-white rounded-xl border border-gray-200 p-5 hover:border-blue-300 hover:shadow-sm transition-all group"
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-2">
                    {(() => { const Icon = CHART_TYPE_ICONS[chart.chart_type]; return <Icon size={16} className="text-blue-500 shrink-0" />; })()}
                    <div>
                      <h2 className="font-semibold text-gray-900 text-sm">{chart.name}</h2>
                      <span className="text-[11px] text-gray-400">{CHART_TYPE_LABELS[chart.chart_type]}</span>
                    </div>
                  </div>
                </div>

                {chart.description && (
                  <p className="text-xs text-gray-500 mb-3 line-clamp-2">{chart.description}</p>
                )}

                <div className="flex items-center justify-between text-xs text-gray-400 mb-4">
                  <span>{chart.node_count} Positionen</span>
                  <span>{new Date(chart.updated_at).toLocaleDateString("de-DE")}</span>
                </div>

                <div className="flex items-center gap-2">
                  <Link
                    href={`/dashboard/org-charts/${chart.id}`}
                    className="flex-1 text-center bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold py-2 rounded-lg transition-colors"
                  >
                    Öffnen
                  </Link>
                  <button
                    onClick={() => handleDelete(chart.id, chart.name)}
                    disabled={deleting === chart.id}
                    className="text-xs text-red-500 hover:text-red-700 px-2 py-2 rounded-lg hover:bg-red-50 transition-colors disabled:opacity-50"
                  >
                    {deleting === chart.id ? "…" : "Löschen"}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
