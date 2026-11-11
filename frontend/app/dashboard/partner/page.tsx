"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";
import {
  placementApi,
  ApiError,
  type PlacementRead,
  type PlacementStats,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { SharePlacementModal } from "@/components/recruiter/SharePlacementModal";

// ── KPI card ──────────────────────────────────────────────────────────────────

function KpiCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: string;
}) {
  return (
    <div className={`rounded-xl border border-gray-200 bg-white p-5 shadow-sm ${accent ?? ""}`}>
      <p className="text-xs font-medium text-gray-500 mb-1">{label}</p>
      <p className="text-2xl font-bold text-gray-900">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}

// ── Placement row ─────────────────────────────────────────────────────────────

function PlacementRow({ p, onShare }: { p: PlacementRead; onShare: (p: PlacementRead) => void }) {
  const date = new Date(p.placed_at).toLocaleDateString("de-DE", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
  });
  return (
    <tr className="border-b border-gray-100 hover:bg-gray-50 transition-colors">
      <td className="py-3 px-4 text-sm text-gray-900">{p.candidate_name ?? "—"}</td>
      <td className="py-3 px-4 text-sm text-gray-700">{p.position_title ?? "—"}</td>
      <td className="py-3 px-4 text-sm text-gray-500">{p.company_name ?? "—"}</td>
      <td className="py-3 px-4 text-sm text-gray-500 text-right">{date}</td>
      <td className="py-3 px-4 text-sm text-right">
        <span className="text-gray-500">{Number(p.commission_pct).toFixed(1)} %</span>
      </td>
      <td className="py-3 px-4 text-sm font-semibold text-right">
        {p.commission_eur != null
          ? <span className="text-green-700">{Number(p.commission_eur).toLocaleString("de-DE", { style: "currency", currency: "EUR" })}</span>
          : <span className="text-gray-400">—</span>}
      </td>
      <td className="py-3 px-2">
        <button
          onClick={() => onShare(p)}
          className="rounded-full border border-[#0077b5]/30 px-2 py-0.5 text-[11px] text-[#0077b5] hover:bg-[#0077b5]/5 transition-colors"
          title="LinkedIn-Post generieren"
        >
          Share
        </button>
      </td>
    </tr>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function PartnerDashboardPage() {
  const router = useRouter();
  const [stats, setStats] = useState<PlacementStats | null>(null);
  const [placements, setPlacements] = useState<PlacementRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sharePlacement, setSharePlacement] = useState<PlacementRead | null>(null);

  const load = useCallback(async () => {
    const token = auth.getAccess();
    if (!token) { router.replace("/login"); return; }
    setLoading(true);
    setError(null);
    try {
      const [s, p] = await Promise.all([
        placementApi.stats(token),
        placementApi.list(token),
      ]);
      setStats(s);
      setPlacements(p);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Fehler beim Laden.");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => { load(); }, [load]);

  const fmtEur = (n: number) =>
    n.toLocaleString("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 });

  return (
    <>

      <main className="max-w-6xl mx-auto px-4 py-8 space-y-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Partner-Dashboard</h1>
            <p className="text-sm text-gray-400 mt-0.5">Provisions-Tracking & Placement-Übersicht</p>
          </div>
          <Button variant="outline" onClick={() => router.push("/dashboard")}>
            ← Recruiter-Dashboard
          </Button>
        </div>

        {error && (
          <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
          </div>
        ) : (
          <>
            {/* KPI row */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4">
              <KpiCard
                label="Placements gesamt"
                value={String(stats?.total_placements ?? 0)}
                sub="Erfolgreich vermittelt"
              />
              <KpiCard
                label="Provision gesamt"
                value={fmtEur(stats?.total_commission_eur ?? 0)}
                sub="Kumuliert"
                accent="border-green-200"
              />
              <KpiCard
                label="Ø Provision / Deal"
                value={fmtEur(stats?.avg_commission_eur ?? 0)}
                sub="Durchschnitt"
              />
              <KpiCard
                label="Ø Provision %"
                value={`${Number(stats?.avg_commission_pct ?? 27.5).toFixed(1)} %`}
                sub="Durchschnittssatz"
              />
              <KpiCard
                label="Placements diesen Monat"
                value={String(stats?.placements_this_month ?? 0)}
                sub="Laufender Monat"
              />
              <KpiCard
                label="Provision diesen Monat"
                value={fmtEur(stats?.commission_this_month ?? 0)}
                sub="Laufender Monat"
                accent="border-blue-200"
              />
            </div>

            {/* Placements table */}
            <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
              <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
                <h2 className="font-semibold text-gray-900">Placements</h2>
                <span className="text-sm text-gray-400">{placements.length} Einträge</span>
              </div>

              {placements.length === 0 ? (
                <div className="py-16 text-center text-sm text-gray-400">
                  Noch keine Placements erfasst.
                  <br />
                  <span className="text-xs">Markiere Kandidaten im Job-Dashboard als platziert.</span>
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-gray-100 bg-gray-50">
                        <th className="py-2.5 px-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Kandidat</th>
                        <th className="py-2.5 px-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Stelle</th>
                        <th className="py-2.5 px-4 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide">Unternehmen</th>
                        <th className="py-2.5 px-4 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">Datum</th>
                        <th className="py-2.5 px-4 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">Prov. %</th>
                        <th className="py-2.5 px-4 text-right text-xs font-semibold text-gray-500 uppercase tracking-wide">Provision €</th>
                        <th className="py-2.5 px-2 text-xs font-semibold text-gray-500 uppercase tracking-wide"></th>
                      </tr>
                    </thead>
                    <tbody>
                      {placements.map((p) => (
                        <PlacementRow key={p.id} p={p} onShare={setSharePlacement} />
                      ))}
                    </tbody>
                    <tfoot>
                      <tr className="border-t border-gray-200 bg-gray-50">
                        <td colSpan={5} className="py-3 px-4 text-sm font-semibold text-gray-700 text-right">
                          Gesamt
                        </td>
                        <td className="py-3 px-4 text-sm font-bold text-green-700 text-right">
                          {fmtEur(stats?.total_commission_eur ?? 0)}
                        </td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              )}
            </div>

            {/* Commission formula info */}
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-800">
              <p className="font-semibold mb-1">Provisions-Berechnung</p>
              <p>Provision = Jahresgehalt × Provisionssatz / 100</p>
              <p className="text-xs text-amber-600 mt-1">
                Standardsatz: 27,5 % — individuell anpassbar pro Placement. Die Berechnung dient nur als Richtwert.
              </p>
            </div>
          </>
        )}
      </main>

      {sharePlacement && (
        <SharePlacementModal
          placement={sharePlacement}
          onClose={() => setSharePlacement(null)}
        />
      )}
    </>
  );
}
