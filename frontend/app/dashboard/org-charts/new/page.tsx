"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { orgChartApi, type OrgChartType } from "@/lib/api";

const TYPES: { value: OrgChartType; label: string; desc: string; icon: string }[] = [
  {
    value: "hierarchical",
    label: "Hierarchisch",
    desc: "Klassische Baumstruktur: CEO → Management → Teams. Ideal für traditionelle Unternehmen.",
    icon: "▼",
  },
  {
    value: "matrix",
    label: "Matrix",
    desc: "Mitarbeiter berichten an zwei Vorgesetzte (z.B. Projekt-Manager + Abteilungsleiter). Für agile Org-Strukturen.",
    icon: "⊞",
  },
  {
    value: "flat",
    label: "Flach",
    desc: "Wenige Hierarchieebenen, alle Mitarbeiter auf Augenhöhe. Typisch für Startups und kleine Teams.",
    icon: "═",
  },
  {
    value: "divisional",
    label: "Divisional",
    desc: "Unternehmensstruktur gruppiert nach Geschäftsbereichen, Regionen oder Produktlinien.",
    icon: "◈",
  },
];

export default function NewOrgChartPage() {
  const router = useRouter();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [chartType, setChartType] = useState<OrgChartType>("hierarchical");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleCreate() {
    if (!name.trim()) { setError("Name ist erforderlich"); return; }
    const token = auth.getToken();
    if (!token) return;
    setCreating(true);
    setError(null);
    try {
      const chart = await orgChartApi.create(token, {
        name: name.trim(),
        description: description.trim() || undefined,
        chart_type: chartType,
      });
      router.push(`/dashboard/org-charts/${chart.id}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Fehler beim Erstellen");
      setCreating(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">

      <div className="max-w-2xl mx-auto px-4 py-10">
        <div className="flex items-center gap-3 mb-8 text-sm">
          <Link href="/dashboard/org-charts" className="text-gray-400 hover:text-gray-600">Organigramme</Link>
          <span className="text-gray-300">/</span>
          <span className="text-gray-600">Neu</span>
        </div>

        <h1 className="text-xl font-bold text-gray-900 mb-6">Neues Organigramm erstellen</h1>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3 mb-5">
            {error}
          </div>
        )}

        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-5">
          <div>
            <label className="text-sm font-medium text-gray-700 block mb-1.5">Name *</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="z.B. Unternehmensstruktur 2026"
              className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div>
            <label className="text-sm font-medium text-gray-700 block mb-1.5">Beschreibung</label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              placeholder="Optional: Kurze Beschreibung des Organigramms"
              className="w-full border border-gray-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
            />
          </div>

          <div>
            <label className="text-sm font-medium text-gray-700 block mb-3">Typ wählen</label>
            <div className="grid grid-cols-2 gap-3">
              {TYPES.map((t) => (
                <button
                  key={t.value}
                  onClick={() => setChartType(t.value)}
                  className={`text-left p-4 rounded-xl border-2 transition-all ${
                    chartType === t.value
                      ? "border-blue-500 bg-blue-50"
                      : "border-gray-200 hover:border-gray-300"
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-lg">{t.icon}</span>
                    <span className="text-sm font-semibold text-gray-900">{t.label}</span>
                  </div>
                  <p className="text-xs text-gray-500 leading-relaxed">{t.desc}</p>
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={handleCreate}
              disabled={creating}
              className="flex-1 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-semibold py-2.5 rounded-lg text-sm transition-colors"
            >
              {creating ? "Erstellen…" : "Organigramm erstellen →"}
            </button>
            <Link
              href="/dashboard/org-charts"
              className="px-4 py-2.5 text-sm text-gray-600 hover:text-gray-900 border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
            >
              Abbrechen
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
