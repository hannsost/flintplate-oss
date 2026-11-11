"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  Plus, X, Wrench, Laptop, Phone, Car, HardHat, Package,
  Search, ChevronRight, ArrowLeftRight, Users,
} from "lucide-react";
import { auth } from "@/lib/auth";
import {
  hrEquipmentApi, EquipmentItemRead, EquipmentAssignmentRead,
  EquipmentItemCreate, AssignItemRequest,
} from "@/lib/api";

// ── Constants ─────────────────────────────────────────────────────────────────

const CATEGORY_META: Record<string, { label: string; icon: React.ReactNode }> = {
  laptop:   { label: "Laptop",    icon: <Laptop className="w-4 h-4" /> },
  phone:    { label: "Telefon",   icon: <Phone className="w-4 h-4" /> },
  vehicle:  { label: "Fahrzeug",  icon: <Car className="w-4 h-4" /> },
  tools:    { label: "Werkzeug",  icon: <Wrench className="w-4 h-4" /> },
  clothing: { label: "Kleidung",  icon: <HardHat className="w-4 h-4" /> },
  other:    { label: "Sonstiges", icon: <Package className="w-4 h-4" /> },
};

const STATUS_META: Record<string, { label: string; color: string }> = {
  available:   { label: "Verfügbar",   color: "bg-green-100 text-green-700" },
  assigned:    { label: "Zugewiesen",  color: "bg-blue-100 text-blue-700" },
  maintenance: { label: "Wartung",     color: "bg-amber-100 text-amber-700" },
  retired:     { label: "Ausgemustert", color: "bg-gray-100 text-gray-500" },
};

const CONDITION_META: Record<string, { label: string }> = {
  new:  { label: "Neu" },
  good: { label: "Gut" },
  fair: { label: "Gebraucht" },
  poor: { label: "Verschlissen" },
};

function fmtDate(iso: string) {
  return new Date(iso + "T00:00:00").toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
}

// ── Add Item Dialog ───────────────────────────────────────────────────────────

function AddItemDialog({
  onSave,
  onClose,
  saving,
}: {
  onSave: (body: EquipmentItemCreate) => void;
  onClose: () => void;
  saving: boolean;
}) {
  const [form, setForm] = useState<EquipmentItemCreate>({
    name: "", category: "other", condition: "good",
  });

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      <div className="fixed z-50 top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white rounded-2xl shadow-2xl p-5 w-full max-w-md">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-gray-900">Ausrüstung hinzufügen</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500"><X className="w-4 h-4" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Name *</label>
            <input value={form.name} onChange={(e) => setForm(f => ({ ...f, name: e.target.value }))}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="z.B. MacBook Pro 14" />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Kategorie</label>
              <select value={form.category} onChange={(e) => setForm(f => ({ ...f, category: e.target.value }))}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                {Object.entries(CATEGORY_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Zustand</label>
              <select value={form.condition} onChange={(e) => setForm(f => ({ ...f, condition: e.target.value }))}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                {Object.entries(CONDITION_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Seriennummer</label>
              <input value={form.serial_number ?? ""} onChange={(e) => setForm(f => ({ ...f, serial_number: e.target.value || undefined }))}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Optional" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Asset-Tag</label>
              <input value={form.asset_tag ?? ""} onChange={(e) => setForm(f => ({ ...f, asset_tag: e.target.value || undefined }))}
                className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Optional" />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Beschreibung</label>
            <textarea value={form.description ?? ""} onChange={(e) => setForm(f => ({ ...f, description: e.target.value || undefined }))}
              rows={2} className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Optional" />
          </div>
        </div>
        <div className="flex gap-2 mt-4">
          <button onClick={onClose} className="flex-1 py-2.5 text-sm text-gray-600 bg-gray-100 rounded-xl hover:bg-gray-200">Abbrechen</button>
          <button disabled={!form.name.trim() || saving} onClick={() => onSave(form)}
            className="flex-1 py-2.5 text-sm text-white bg-blue-600 rounded-xl hover:bg-blue-700 disabled:opacity-40">
            {saving ? "Wird gespeichert..." : "Hinzufügen"}
          </button>
        </div>
      </div>
    </>
  );
}

// ── Assign Dialog ─────────────────────────────────────────────────────────────

function AssignDialog({
  item,
  workers,
  onSave,
  onClose,
  saving,
}: {
  item: EquipmentItemRead;
  workers: { id: string; name: string; email: string }[];
  onSave: (body: AssignItemRequest) => void;
  onClose: () => void;
  saving: boolean;
}) {
  const today = new Date().toISOString().split("T")[0];
  const [workerId, setWorkerId] = useState("");
  const [assignedAt, setAssignedAt] = useState(today);
  const [notes, setNotes] = useState("");

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/30" onClick={onClose} />
      <div className="fixed z-50 top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 bg-white rounded-2xl shadow-2xl p-5 w-full max-w-sm">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-gray-900">Zuweisen: {item.name}</h3>
          <button onClick={onClose} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500"><X className="w-4 h-4" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Mitarbeiter *</label>
            <select value={workerId} onChange={(e) => setWorkerId(e.target.value)}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="">Auswählen...</option>
              {workers.map((w) => <option key={w.id} value={w.id}>{w.name || w.email}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Datum *</label>
            <input type="date" value={assignedAt} onChange={(e) => setAssignedAt(e.target.value)}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Notiz</label>
            <input value={notes} onChange={(e) => setNotes(e.target.value)}
              className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Optional" />
          </div>
        </div>
        <div className="flex gap-2 mt-4">
          <button onClick={onClose} className="flex-1 py-2.5 text-sm text-gray-600 bg-gray-100 rounded-xl hover:bg-gray-200">Abbrechen</button>
          <button disabled={!workerId || !assignedAt || saving} onClick={() => onSave({ worker_id: workerId, assigned_at: assignedAt, notes: notes || undefined })}
            className="flex-1 py-2.5 text-sm text-white bg-blue-600 rounded-xl hover:bg-blue-700 disabled:opacity-40">
            {saving ? "Wird zugewiesen..." : "Zuweisen"}
          </button>
        </div>
      </div>
    </>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function HREquipmentPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [items, setItems] = useState<EquipmentItemRead[]>([]);
  const [assignments, setAssignments] = useState<EquipmentAssignmentRead[]>([]);
  const [workers, setWorkers] = useState<{ id: string; name: string; email: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [assignTarget, setAssignTarget] = useState<EquipmentItemRead | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [tab, setTab] = useState<"items" | "assignments">("items");

  useEffect(() => {
    const t = auth.getAccess();
    if (!t) { router.replace("/login"); return; }
    setToken(t);
  }, [router]);

  const load = useCallback(async (t: string) => {
    setLoading(true);
    try {
      const [itemList, assignList] = await Promise.all([
        hrEquipmentApi.listItems(t),
        hrEquipmentApi.listAssignments(t, { active_only: false }),
      ]);
      setItems(itemList);
      setAssignments(assignList);

      // Derive unique workers from assignments for the assign dialog
      const seen = new Set<string>();
      const ws: { id: string; name: string; email: string }[] = [];
      for (const a of assignList) {
        if (!seen.has(a.worker_id)) {
          seen.add(a.worker_id);
          ws.push({ id: a.worker_id, name: a.worker_name ?? "", email: a.worker_email });
        }
      }
      setWorkers(ws);
    } catch { setItems([]); setAssignments([]); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (token) load(token); }, [token, load]);

  async function handleAddItem(body: EquipmentItemCreate) {
    if (!token) return;
    setSaving(true);
    try {
      const item = await hrEquipmentApi.createItem(token, body);
      setItems((prev) => [item, ...prev]);
      setShowAdd(false);
    } catch { /* ignore */ }
    finally { setSaving(false); }
  }

  async function handleAssign(body: AssignItemRequest) {
    if (!token || !assignTarget) return;
    setSaving(true);
    try {
      await hrEquipmentApi.assign(token, assignTarget.id, body);
      setAssignTarget(null);
      load(token);
    } catch { /* ignore */ }
    finally { setSaving(false); }
  }

  async function handleReturn(item: EquipmentItemRead) {
    if (!token) return;
    const today = new Date().toISOString().split("T")[0];
    setSaving(true);
    try {
      await hrEquipmentApi.returnItem(token, item.id, today);
      load(token);
    } catch { /* ignore */ }
    finally { setSaving(false); }
  }

  async function handleDelete(item: EquipmentItemRead) {
    if (!token || !confirm(`"${item.name}" löschen?`)) return;
    try {
      await hrEquipmentApi.deleteItem(token, item.id);
      setItems((prev) => prev.filter((i) => i.id !== item.id));
    } catch { /* ignore */ }
  }

  const filteredItems = items.filter((i) => {
    if (statusFilter && i.status !== statusFilter) return false;
    if (search && !i.name.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const activeAssignments = assignments.filter((a) => !a.returned_at);

  return (
    <div className="min-h-screen bg-gray-50 p-4 md:p-6">
      <div className="max-w-5xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Ausrüstung</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              {items.length} Objekte · {activeAssignments.length} zugewiesen
            </p>
          </div>
          <button onClick={() => setShowAdd(true)}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-xl hover:bg-blue-700">
            <Plus className="w-4 h-4" /> Hinzufügen
          </button>
        </div>

        {/* Tabs */}
        <div className="flex gap-1 bg-gray-100 rounded-xl p-1 mb-5 w-fit">
          <button onClick={() => setTab("items")}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${tab === "items" ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"}`}>
            Inventar
          </button>
          <button onClick={() => setTab("assignments")}
            className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${tab === "assignments" ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700"}`}>
            Zuweisungen <span className="ml-1 text-xs text-blue-600 font-semibold">{activeAssignments.length}</span>
          </button>
        </div>

        {tab === "items" && (
          <>
            {/* Filters */}
            <div className="bg-white border border-gray-200 rounded-xl px-4 py-3 flex flex-wrap items-center gap-3 mb-4">
              <div className="relative flex-1 min-w-[160px]">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                <input value={search} onChange={(e) => setSearch(e.target.value)}
                  placeholder="Suchen..."
                  className="w-full pl-8 pr-3 py-2 text-sm border border-gray-300 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500" />
              </div>
              <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
                className="border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="">Alle Status</option>
                {Object.entries(STATUS_META).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
              </select>
            </div>

            {loading ? (
              <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Lade...</div>
            ) : filteredItems.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-40 text-gray-400 gap-2">
                <Wrench className="w-8 h-8 text-gray-200" />
                <p className="text-sm">Keine Ausrüstung gefunden</p>
              </div>
            ) : (
              <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-100 bg-gray-50 text-xs text-gray-500 font-medium">
                      <th className="px-4 py-2.5 text-left">Name</th>
                      <th className="px-4 py-2.5 text-left">Kategorie</th>
                      <th className="px-4 py-2.5 text-left">Status</th>
                      <th className="px-4 py-2.5 text-left">Zustand</th>
                      <th className="px-4 py-2.5 text-left">Seriennr.</th>
                      <th className="px-4 py-2.5" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {filteredItems.map((item) => {
                      const cat = CATEGORY_META[item.category] ?? CATEGORY_META.other;
                      const st = STATUS_META[item.status] ?? STATUS_META.available;
                      const cond = CONDITION_META[item.condition] ?? CONDITION_META.good;

                      return (
                        <tr key={item.id} className="hover:bg-gray-50">
                          <td className="px-4 py-3 font-medium text-gray-900">{item.name}</td>
                          <td className="px-4 py-3">
                            <span className="inline-flex items-center gap-1.5 text-gray-600">
                              {cat.icon}{cat.label}
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${st.color}`}>
                              {st.label}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-gray-500 text-xs">{cond.label}</td>
                          <td className="px-4 py-3 font-mono text-xs text-gray-500">{item.serial_number ?? "–"}</td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-1 justify-end">
                              {item.status === "available" && (
                                <button onClick={() => setAssignTarget(item)}
                                  className="flex items-center gap-1 px-2.5 py-1 text-xs text-blue-600 bg-blue-50 rounded-lg hover:bg-blue-100">
                                  <Users className="w-3 h-3" /> Zuweisen
                                </button>
                              )}
                              {item.status === "assigned" && (
                                <button onClick={() => handleReturn(item)} disabled={saving}
                                  className="flex items-center gap-1 px-2.5 py-1 text-xs text-amber-600 bg-amber-50 rounded-lg hover:bg-amber-100 disabled:opacity-40">
                                  <ArrowLeftRight className="w-3 h-3" /> Zurück
                                </button>
                              )}
                              {item.status !== "assigned" && (
                                <button onClick={() => handleDelete(item)}
                                  className="p-1.5 text-gray-300 hover:text-red-500 rounded-lg hover:bg-red-50">
                                  <X className="w-3.5 h-3.5" />
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}

        {tab === "assignments" && (
          <div className="space-y-2">
            {activeAssignments.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-40 text-gray-400 gap-2">
                <Users className="w-8 h-8 text-gray-200" />
                <p className="text-sm">Keine aktiven Zuweisungen</p>
              </div>
            ) : activeAssignments.map((a) => (
              <div key={a.id} className="bg-white border border-gray-200 rounded-xl p-4 flex items-center gap-4">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900">{a.item?.name ?? "–"}</p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    {a.worker_name ?? a.worker_email} · seit {fmtDate(a.assigned_at)}
                  </p>
                  {a.notes && <p className="text-xs text-gray-400 italic mt-0.5">&quot;{a.notes}&quot;</p>}
                </div>
                <ChevronRight className="w-4 h-4 text-gray-300" />
              </div>
            ))}
          </div>
        )}
      </div>

      {showAdd && <AddItemDialog onSave={handleAddItem} onClose={() => setShowAdd(false)} saving={saving} />}
      {assignTarget && (
        <AssignDialog
          item={assignTarget}
          workers={workers}
          onSave={handleAssign}
          onClose={() => setAssignTarget(null)}
          saving={saving}
        />
      )}
    </div>
  );
}
