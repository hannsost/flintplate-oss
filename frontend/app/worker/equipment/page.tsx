"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Wrench, Laptop, Phone, Car, HardHat, Package } from "lucide-react";
import { auth } from "@/lib/auth";
import { workerEquipmentApi, EquipmentAssignmentRead } from "@/lib/api";

// ── Helpers ───────────────────────────────────────────────────────────────────

const CATEGORY_META: Record<string, { label: string; icon: React.ReactNode; color: string }> = {
  laptop:   { label: "Laptop",      icon: <Laptop className="w-5 h-5" />,  color: "text-blue-600 bg-blue-50" },
  phone:    { label: "Telefon",     icon: <Phone className="w-5 h-5" />,   color: "text-green-600 bg-green-50" },
  vehicle:  { label: "Fahrzeug",    icon: <Car className="w-5 h-5" />,     color: "text-purple-600 bg-purple-50" },
  tools:    { label: "Werkzeug",    icon: <Wrench className="w-5 h-5" />,  color: "text-amber-600 bg-amber-50" },
  clothing: { label: "Kleidung",    icon: <HardHat className="w-5 h-5" />, color: "text-red-600 bg-red-50" },
  other:    { label: "Sonstiges",   icon: <Package className="w-5 h-5" />, color: "text-gray-600 bg-gray-100" },
};

const CONDITION_LABELS: Record<string, { label: string; color: string }> = {
  new:  { label: "Neu",       color: "bg-green-100 text-green-700" },
  good: { label: "Gut",       color: "bg-blue-100 text-blue-700" },
  fair: { label: "Gebraucht", color: "bg-amber-100 text-amber-700" },
  poor: { label: "Verschlissen", color: "bg-red-100 text-red-700" },
};

function fmtDate(iso: string) {
  return new Date(iso + "T00:00:00").toLocaleDateString("de-DE", { day: "2-digit", month: "2-digit", year: "numeric" });
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function WorkerEquipmentPage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [assignments, setAssignments] = useState<EquipmentAssignmentRead[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const t = auth.getAccess();
    if (!t) { router.replace("/login"); return; }
    setToken(t);
  }, [router]);

  const load = useCallback(async (t: string) => {
    setLoading(true);
    try {
      const list = await workerEquipmentApi.list(t);
      setAssignments(list);
    } catch { setAssignments([]); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (token) load(token); }, [token, load]);

  return (
    <div className="min-h-screen bg-gray-50 p-4 md:p-6">
      <div className="max-w-2xl mx-auto">
        {/* Header */}
        <div className="mb-5">
          <h1 className="text-xl font-semibold text-gray-900">Meine Ausrüstung</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Zugewiesene Geräte und Materialien · {assignments.length} Objekt{assignments.length !== 1 ? "e" : ""}
          </p>
        </div>

        {loading ? (
          <div className="flex items-center justify-center h-40 text-gray-400 text-sm">Lade...</div>
        ) : assignments.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-gray-400 gap-2">
            <Wrench className="w-8 h-8 text-gray-200" />
            <p className="text-sm">Keine Ausrüstung zugewiesen</p>
          </div>
        ) : (
          <div className="space-y-3">
            {assignments.map((a) => {
              const cat = CATEGORY_META[a.item?.category ?? "other"] ?? CATEGORY_META.other;
              const cond = CONDITION_LABELS[a.item?.condition ?? "good"] ?? CONDITION_LABELS.good;

              return (
                <div key={a.id} className="bg-white border border-gray-200 rounded-xl p-4 flex items-start gap-4">
                  <div className={`p-2.5 rounded-xl ${cat.color} flex-shrink-0`}>
                    {cat.icon}
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-2">
                      <div>
                        <p className="text-sm font-medium text-gray-900">{a.item?.name ?? "–"}</p>
                        <p className="text-xs text-gray-500 mt-0.5">{cat.label}</p>
                      </div>
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${cond.color}`}>
                        {cond.label}
                      </span>
                    </div>

                    <div className="mt-2 space-y-1">
                      {a.item?.serial_number && (
                        <p className="text-xs text-gray-500">
                          Seriennummer: <span className="font-mono text-gray-700">{a.item.serial_number}</span>
                        </p>
                      )}
                      {a.item?.asset_tag && (
                        <p className="text-xs text-gray-500">
                          Asset-Tag: <span className="font-mono text-gray-700">{a.item.asset_tag}</span>
                        </p>
                      )}
                      <p className="text-xs text-gray-500">
                        Zugewiesen am {fmtDate(a.assigned_at)}
                        {a.assigned_by_name && ` von ${a.assigned_by_name}`}
                      </p>
                      {a.notes && (
                        <p className="text-xs text-gray-400 italic">&quot;{a.notes}&quot;</p>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
