"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Receipt, Download, ChevronLeft, ChevronRight, TrendingUp } from "lucide-react";
import { auth } from "@/lib/auth";
import { workerPayrollApi, PayStubRead } from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtEur(cents: number): string {
  return (cents / 100).toLocaleString("de-DE", { style: "currency", currency: "EUR" });
}

function currentYear() { return new Date().getFullYear(); }

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function WorkerPayrollPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [year, setYear] = useState(currentYear());
  const [stubs, setStubs] = useState<PayStubRead[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const t = auth.getAccess();
    if (!t) { router.replace("/login"); return; }
    setToken(t);
  }, [router]);

  const load = useCallback(async (t: string, y: number) => {
    setLoading(true);
    try {
      const list = await workerPayrollApi.list(t, y);
      setStubs(list);
    } catch { setStubs([]); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (token) load(token, year); }, [token, year, load]);

  const totalNet = stubs.reduce((s, p) => s + p.net_cents, 0);
  const totalGross = stubs.reduce((s, p) => s + p.gross_cents, 0);

  return (
    <div className="min-h-screen bg-gray-50 p-4 md:p-6">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="mb-5">
          <h1 className="text-xl font-semibold text-gray-900">Lohnabrechnung</h1>
          <p className="text-sm text-gray-500 mt-0.5">Monatliche Gehaltsabrechnungen</p>
        </div>

        {/* Year nav */}
        <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 flex items-center justify-between mb-4">
          <button onClick={() => setYear(y => y - 1)} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500">
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-sm font-semibold text-gray-800">{year}</span>
          <button onClick={() => setYear(y => y + 1)} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500">
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>

        {/* Year summary */}
        {stubs.length > 0 && (
          <div className="grid grid-cols-2 gap-3 mb-5">
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <p className="text-xs text-gray-500 mb-1 flex items-center gap-1"><TrendingUp className="w-3 h-3" /> Brutto Gesamt</p>
              <p className="text-lg font-bold text-gray-900">{fmtEur(totalGross)}</p>
            </div>
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <p className="text-xs text-gray-500 mb-1 flex items-center gap-1"><Receipt className="w-3 h-3" /> Netto Gesamt</p>
              <p className="text-lg font-bold text-green-600">{fmtEur(totalNet)}</p>
            </div>
          </div>
        )}

        {/* List */}
        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Lade...</div>
        ) : stubs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-gray-400 gap-2">
            <Receipt className="w-8 h-8 text-gray-200" />
            <p className="text-sm">Keine Abrechnungen in {year}</p>
          </div>
        ) : (
          <div className="space-y-2">
            {stubs.map((stub) => (
              <div key={stub.id} className="bg-white border border-gray-200 rounded-xl p-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1">
                    <p className="text-sm font-semibold text-gray-900">{stub.period_label}</p>
                    <div className="flex items-center gap-4 mt-2">
                      <div>
                        <p className="text-xs text-gray-400">Brutto</p>
                        <p className="text-sm font-medium text-gray-700">{fmtEur(stub.gross_cents)}</p>
                      </div>
                      <div>
                        <p className="text-xs text-gray-400">Netto</p>
                        <p className="text-sm font-medium text-green-600">{fmtEur(stub.net_cents)}</p>
                      </div>
                      {stub.tax_cents > 0 && (
                        <div>
                          <p className="text-xs text-gray-400">Steuer</p>
                          <p className="text-sm font-medium text-gray-500">{fmtEur(stub.tax_cents)}</p>
                        </div>
                      )}
                      {stub.hours_worked && (
                        <div>
                          <p className="text-xs text-gray-400">Stunden</p>
                          <p className="text-sm font-medium text-gray-600">{Number(stub.hours_worked).toFixed(1)} h</p>
                        </div>
                      )}
                    </div>
                    {stub.notes && (
                      <p className="text-xs text-gray-400 mt-1.5 italic">{stub.notes}</p>
                    )}
                  </div>
                  {stub.document_url && (
                    <a href={stub.document_url} target="_blank" rel="noopener noreferrer"
                      className="flex-shrink-0 p-2 rounded-lg text-gray-400 hover:text-blue-600 hover:bg-blue-50"
                      title="PDF herunterladen">
                      <Download className="w-4 h-4" />
                    </a>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
