"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";
import { zeitarbeitApi, ApiError, type AvailabilityRead } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { AlertTriangle, Check, Calendar, Clock, MapPin, Car } from "lucide-react";

// ── AÜG compliance badge ──────────────────────────────────────────────────────

function AuegBadge({ av }: { av: AvailabilityRead }) {
  const pct = Math.min(100, (Number(av.total_placed_months) / 18) * 100);
  const colors = {
    green:  { bar: "bg-green-500", text: "text-green-700", bg: "bg-green-50 border-green-200" },
    yellow: { bar: "bg-yellow-400", text: "text-yellow-700", bg: "bg-yellow-50 border-yellow-200" },
    red:    { bar: "bg-red-500", text: "text-red-700", bg: "bg-red-50 border-red-200" },
  };
  const c = colors[av.aueg_status];

  return (
    <div className={`rounded-lg border p-3 ${c.bg}`}>
      <div className="flex items-center justify-between mb-1.5">
        <p className="text-xs font-semibold text-gray-600">AÜG-Überlassung</p>
        <span className={`text-xs font-bold ${c.text}`}>
          {Number(av.total_placed_months).toFixed(1)} / 18 Monate
        </span>
      </div>
      <div className="h-2 rounded-full bg-gray-200 overflow-hidden">
        <div className={`h-full rounded-full transition-all ${c.bar}`} style={{ width: `${pct}%` }} />
      </div>
      <p className={`text-xs mt-1 ${c.text}`}>
        {av.aueg_status === "red"
          ? <><AlertTriangle size={11} className="inline mr-0.5" />Höchstüberlassungsdauer erreicht</>
          : av.aueg_status === "yellow"
          ? <><AlertTriangle size={11} className="inline mr-0.5" />Noch {Number(av.aueg_remaining_months).toFixed(1)} Monate verfügbar</>
          : <><Check size={11} className="inline mr-0.5" />{Number(av.aueg_remaining_months).toFixed(1)} Monate verbleibend</>}
      </p>
    </div>
  );
}

// ── Pool worker row ───────────────────────────────────────────────────────────

function PoolRow({ av }: { av: AvailabilityRead }) {
  const shiftLabel: Record<string, string> = { day: "Tagschicht", night: "Nachtschicht", flexible: "Flexibel" };
  const statusDot = av.aueg_status === "red" ? "bg-red-500" : av.aueg_status === "yellow" ? "bg-yellow-400" : "bg-blue-500";

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4 space-y-3 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${statusDot}`} />
            <p className="font-medium text-gray-900 text-sm">Mitarbeiter-ID: {av.user_id.slice(0, 8)}…</p>
          </div>
          <div className="mt-1 flex flex-wrap gap-3 text-xs text-gray-500">
            {av.available_from && (
              <span className="flex items-center gap-1"><Calendar size={11} />ab {new Date(av.available_from).toLocaleDateString("de-DE")}</span>
            )}
            {av.available_until && (
              <span>bis {new Date(av.available_until).toLocaleDateString("de-DE")}</span>
            )}
            {av.preferred_shift && (
              <span className="flex items-center gap-1"><Clock size={11} />{shiftLabel[av.preferred_shift] ?? av.preferred_shift}</span>
            )}
            {av.preferred_location && (
              <span className="flex items-center gap-1"><MapPin size={11} />{av.preferred_location}</span>
            )}
            {av.max_commute_km && (
              <span className="flex items-center gap-1"><Car size={11} />max. {av.max_commute_km} km</span>
            )}
          </div>
        </div>
      </div>
      <AuegBadge av={av} />
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function PoolPage() {
  const router = useRouter();
  const [pool, setPool] = useState<AvailabilityRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = auth.getAccess();
    if (!token) { router.replace("/login"); return; }
    setLoading(true);
    setError(null);
    try {
      setPool(await zeitarbeitApi.getPool(token));
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Fehler beim Laden.");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => { load(); }, [load]);

  const redCount    = pool.filter((a) => a.aueg_status === "red").length;
  const yellowCount = pool.filter((a) => a.aueg_status === "yellow").length;
  const greenCount  = pool.filter((a) => a.aueg_status === "green").length;

  return (
    <>

      <main className="max-w-4xl mx-auto px-4 py-8 space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Zeitarbeiter-Pool</h1>
            <p className="text-sm text-gray-400 mt-0.5">Verfügbarkeit & AÜG-Compliance-Übersicht</p>
          </div>
          <Button variant="outline" onClick={() => router.push("/dashboard/zeitarbeit")}>
            ← Aufträge
          </Button>
        </div>

        {error && (
          <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">{error}</div>
        )}

        {/* Compliance summary */}
        {pool.length > 0 && (
          <div className="grid grid-cols-3 gap-4">
            <div className="rounded-xl border border-green-200 bg-green-50 p-4 text-center">
              <p className="text-2xl font-bold text-green-700">{greenCount}</p>
              <p className="text-xs text-green-600 mt-0.5 flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-blue-500 inline-block" />Verfügbar</p>
            </div>
            <div className="rounded-xl border border-yellow-200 bg-yellow-50 p-4 text-center">
              <p className="text-2xl font-bold text-yellow-700">{yellowCount}</p>
              <p className="text-xs text-yellow-600 mt-0.5 flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-yellow-400 inline-block" />Bald Limit</p>
            </div>
            <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-center">
              <p className="text-2xl font-bold text-red-700">{redCount}</p>
              <p className="text-xs text-red-600 mt-0.5 flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500 inline-block" />Limit erreicht</p>
            </div>
          </div>
        )}

        {loading ? (
          <div className="flex justify-center py-12">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
          </div>
        ) : pool.length === 0 ? (
          <div className="rounded-xl border border-gray-200 bg-white py-16 text-center">
            <p className="text-gray-500">Noch keine Mitarbeiter im Pool.</p>
            <p className="text-sm text-gray-400 mt-1">
              Kandidaten können ihre Verfügbarkeit im Profil hinterlegen.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {pool.map((av) => <PoolRow key={av.id} av={av} />)}
          </div>
        )}

        {/* AÜG info box */}
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm text-amber-800">
          <p className="font-semibold mb-1">AÜG § 1 Abs. 1b – Höchstüberlassungsdauer</p>
          <p>Arbeitnehmer dürfen maximal <strong>18 aufeinanderfolgende Monate</strong> beim selben Entleiher eingesetzt werden.</p>
          <p className="text-xs text-amber-600 mt-1">
            <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-yellow-400" />Warnung ab 15 Monaten</span> · <span className="inline-flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500" />Limit erreicht — kein Einsatz mehr möglich</span>
          </p>
        </div>
      </main>
    </>
  );
}
