"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Plus, X, Receipt, Send, Trash2, Search, ChevronLeft, ChevronRight,
} from "lucide-react";
import { auth } from "@/lib/auth";
import { hrPayrollApi, PayStubRead, PayStubCreate } from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

function fmtEur(cents: number): string {
  return (cents / 100).toLocaleString("de-DE", { style: "currency", currency: "EUR" });
}

function currentYear() { return new Date().getFullYear(); }

const MONTHS = [
  "Januar","Februar","März","April","Mai","Juni",
  "Juli","August","September","Oktober","November","Dezember",
];

// ── Create Dialog ─────────────────────────────────────────────────────────────

function CreateStubDialog({
  workers,
  onSave,
  onClose,
  saving,
}: {
  workers: { id: string; name: string; email: string }[];
  onSave: (body: PayStubCreate) => void;
  onClose: () => void;
  saving: boolean;
}) {
  const now = new Date();
  const [form, setForm] = useState({
    worker_id: "",
    period_year: now.getFullYear(),
    period_month: now.getMonth() + 1,
    gross: "",
    net: "",
    tax: "",
    sv: "",
    hours: "",
    overtime: "",
    document_url: "",
    notes: "",
  });

  function toBody(): PayStubCreate {
    return {
      worker_id: form.worker_id,
      period_year: form.period_year,
      period_month: form.period_month,
      gross_cents: Math.round(parseFloat(form.gross) * 100),
      net_cents: Math.round(parseFloat(form.net) * 100),
      tax_cents: form.tax ? Math.round(parseFloat(form.tax) * 100) : 0,
      social_security_cents: form.sv ? Math.round(parseFloat(form.sv) * 100) : 0,
      hours_worked: form.hours ? parseFloat(form.hours) : undefined,
      overtime_hours: form.overtime ? parseFloat(form.overtime) : undefined,
      document_url: form.document_url || undefined,
      notes: form.notes || undefined,
    };
  }

  const valid = form.worker_id && form.gross && form.net &&
    !isNaN(parseFloat(form.gross)) && !isNaN(parseFloat(form.net));

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      <div className="fixed z-50 top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white rounded-2xl shadow-2xl p-5 w-full max-w-lg max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-gray-900">Lohnabrechnung erstellen</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500"><X className="w-4 h-4" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Mitarbeiter *</label>
            <select value={form.worker_id} onChange={(e) => setForm(f => ({ ...f, worker_id: e.target.value }))}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="">Auswählen...</option>
              {workers.map((w) => <option key={w.id} value={w.id}>{w.name || w.email}</option>)}
            </select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Monat *</label>
              <select value={form.period_month} onChange={(e) => setForm(f => ({ ...f, period_month: Number(e.target.value) }))}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                {MONTHS.map((m, i) => <option key={i+1} value={i+1}>{m}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Jahr *</label>
              <input type="number" value={form.period_year} onChange={(e) => setForm(f => ({ ...f, period_year: Number(e.target.value) }))}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Brutto (€) *</label>
              <input type="number" step="0.01" value={form.gross} onChange={(e) => setForm(f => ({ ...f, gross: e.target.value }))}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="3200.00" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Netto (€) *</label>
              <input type="number" step="0.01" value={form.net} onChange={(e) => setForm(f => ({ ...f, net: e.target.value }))}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="2100.00" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Steuer (€)</label>
              <input type="number" step="0.01" value={form.tax} onChange={(e) => setForm(f => ({ ...f, tax: e.target.value }))}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Optional" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">SV-Anteil (€)</label>
              <input type="number" step="0.01" value={form.sv} onChange={(e) => setForm(f => ({ ...f, sv: e.target.value }))}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Optional" />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Arbeitsstunden</label>
              <input type="number" step="0.5" value={form.hours} onChange={(e) => setForm(f => ({ ...f, hours: e.target.value }))}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="160.0" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Überstunden</label>
              <input type="number" step="0.5" value={form.overtime} onChange={(e) => setForm(f => ({ ...f, overtime: e.target.value }))}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="0.0" />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">PDF-URL</label>
            <input value={form.document_url} onChange={(e) => setForm(f => ({ ...f, document_url: e.target.value }))}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="https://... (optional)" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Notiz</label>
            <input value={form.notes} onChange={(e) => setForm(f => ({ ...f, notes: e.target.value }))}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Optional" />
          </div>
        </div>
        <div className="flex gap-2 mt-4">
          <button onClick={onClose} className="flex-1 py-2.5 text-sm text-gray-600 bg-gray-100 rounded-xl hover:bg-gray-200">Abbrechen</button>
          <button disabled={!valid || saving} onClick={() => onSave(toBody())}
            className="flex-1 py-2.5 text-sm text-white bg-blue-600 rounded-xl hover:bg-blue-700 disabled:opacity-40">
            {saving ? "Wird erstellt..." : "Erstellen (Entwurf)"}
          </button>
        </div>
      </div>
    </>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function HRPayrollPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [year, setYear] = useState(currentYear());
  const [stubs, setStubs] = useState<PayStubRead[]>([]);
  const [workers, setWorkers] = useState<{ id: string; name: string; email: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [workerFilter, setWorkerFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");

  useEffect(() => {
    const t = auth.getAccess();
    if (!t) { router.replace("/login"); return; }
    setToken(t);
  }, [router]);

  const load = useCallback(async (t: string, y: number) => {
    setLoading(true);
    try {
      const list = await hrPayrollApi.list(t, { year: y });
      setStubs(list);
      const seen = new Set<string>();
      const ws: { id: string; name: string; email: string }[] = [];
      for (const s of list) {
        if (!seen.has(s.worker_id)) {
          seen.add(s.worker_id);
          ws.push({ id: s.worker_id, name: s.worker_name ?? "", email: s.worker_email });
        }
      }
      setWorkers(ws);
    } catch { setStubs([]); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (token) load(token, year); }, [token, year, load]);

  async function handleCreate(body: PayStubCreate) {
    if (!token) return;
    setSaving(true);
    try {
      const stub = await hrPayrollApi.create(token, body);
      setStubs((prev) => [stub, ...prev]);
      setShowCreate(false);
    } catch { /* ignore */ }
    finally { setSaving(false); }
  }

  async function handlePublish(stub: PayStubRead) {
    if (!token || !confirm(`Abrechnung "${stub.period_label}" veröffentlichen? Der Mitarbeiter kann sie dann einsehen.`)) return;
    try {
      const updated = await hrPayrollApi.publish(token, stub.id);
      setStubs((prev) => prev.map((s) => s.id === updated.id ? updated : s));
    } catch { /* ignore */ }
  }

  async function handleDelete(stub: PayStubRead) {
    if (!token || !confirm(`Entwurf "${stub.period_label}" löschen?`)) return;
    try {
      await hrPayrollApi.delete(token, stub.id);
      setStubs((prev) => prev.filter((s) => s.id !== stub.id));
    } catch { /* ignore */ }
  }

  const filtered = stubs.filter((s) => {
    if (workerFilter && s.worker_id !== workerFilter) return false;
    if (statusFilter && s.status !== statusFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      if (!s.worker_name?.toLowerCase().includes(q) && !s.worker_email.toLowerCase().includes(q)) return false;
    }
    return true;
  });

  const draftCount = stubs.filter((s) => s.status === "draft").length;

  return (
    <div className="min-h-screen bg-gray-50 p-4 md:p-6">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Lohnabrechnung</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              {stubs.length} Abrechnungen
              {draftCount > 0 && <span className="text-amber-600 font-medium"> · {draftCount} Entwurf{draftCount !== 1 ? "e" : ""}</span>}
            </p>
          </div>
          <button onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-xl hover:bg-blue-700">
            <Plus className="w-4 h-4" /> Abrechnung
          </button>
        </div>

        {/* Filters */}
        <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 flex flex-wrap items-center gap-3 mb-5">
          <div className="flex items-center gap-1">
            <button onClick={() => setYear(y => y - 1)} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500">
              <ChevronLeft className="w-4 h-4" />
            </button>
            <span className="text-sm font-semibold text-gray-800 w-10 text-center">{year}</span>
            <button onClick={() => setYear(y => y + 1)} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500">
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
          <div className="h-5 w-px bg-gray-200" />
          <div className="relative flex-1 min-w-[160px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Mitarbeiter suchen..."
              className="w-full pl-8 pr-3 py-2 text-sm border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
            className="border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="">Alle</option>
            <option value="draft">Entwurf</option>
            <option value="published">Veröffentlicht</option>
          </select>
          {workers.length > 0 && (
            <select value={workerFilter} onChange={(e) => setWorkerFilter(e.target.value)}
              className="border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="">Alle Mitarbeiter</option>
              {workers.map((w) => <option key={w.id} value={w.id}>{w.name || w.email}</option>)}
            </select>
          )}
        </div>

        {/* Table */}
        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Lade...</div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-gray-400 gap-2">
            <Receipt className="w-8 h-8 text-gray-200" />
            <p className="text-sm">Keine Abrechnungen gefunden</p>
          </div>
        ) : (
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50 text-xs text-gray-500 font-medium">
                  <th className="px-4 py-2.5 text-left">Mitarbeiter</th>
                  <th className="px-4 py-2.5 text-left">Zeitraum</th>
                  <th className="px-4 py-2.5 text-right">Brutto</th>
                  <th className="px-4 py-2.5 text-right">Netto</th>
                  <th className="px-4 py-2.5 text-left">Status</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {filtered.map((stub) => (
                  <tr key={stub.id} className="hover:bg-gray-50">
                    <td className="px-4 py-3 font-medium text-gray-900">
                      {stub.worker_name ?? stub.worker_email}
                    </td>
                    <td className="px-4 py-3 text-gray-600">{stub.period_label}</td>
                    <td className="px-4 py-3 text-right text-gray-700">{fmtEur(stub.gross_cents)}</td>
                    <td className="px-4 py-3 text-right font-medium text-green-600">{fmtEur(stub.net_cents)}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${
                        stub.status === "published" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"
                      }`}>
                        {stub.status === "published" ? "Veröffentlicht" : "Entwurf"}
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-1 justify-end">
                        {stub.status === "draft" && (
                          <>
                            <button onClick={() => handlePublish(stub)}
                              className="flex items-center gap-1 px-2.5 py-1 text-xs text-green-700 bg-green-50 rounded-lg hover:bg-green-100"
                              title="Veröffentlichen">
                              <Send className="w-3 h-3" /> Senden
                            </button>
                            <button onClick={() => handleDelete(stub)}
                              className="p-1.5 text-gray-300 hover:text-red-500 rounded-lg hover:bg-red-50">
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {showCreate && (
        <CreateStubDialog
          workers={workers}
          onSave={handleCreate}
          onClose={() => setShowCreate(false)}
          saving={saving}
        />
      )}
    </div>
  );
}
