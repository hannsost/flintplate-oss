"use client";

import { useEffect, useState } from "react";
import { auth } from "@/lib/auth";
import { zeitarbeitApi, type AvailabilityRead } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function AvailabilityWidget() {
  const [open, setOpen] = useState(false);
  const [av, setAv] = useState<AvailabilityRead | null>(null);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    is_in_pool: false,
    available_from: "",
    available_until: "",
    preferred_shift: "flexible",
    preferred_location: "",
    max_commute_km: "",
  });

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) return;
    zeitarbeitApi.getMyAvailability(token)
      .then((data) => {
        if (data) {
          setAv(data);
          setForm({
            is_in_pool: data.is_in_pool,
            available_from: data.available_from ?? "",
            available_until: data.available_until ?? "",
            preferred_shift: data.preferred_shift ?? "flexible",
            preferred_location: data.preferred_location ?? "",
            max_commute_km: data.max_commute_km != null ? String(data.max_commute_km) : "",
          });
        }
      })
      .catch(() => {});
  }, []);

  async function handleSave() {
    const token = auth.getAccess();
    if (!token) return;
    setSaving(true);
    try {
      const updated = await zeitarbeitApi.setMyAvailability(token, {
        is_in_pool: form.is_in_pool,
        available_from: form.available_from || null,
        available_until: form.available_until || null,
        preferred_shift: form.preferred_shift || null,
        preferred_location: form.preferred_location || null,
        max_commute_km: form.max_commute_km ? parseInt(form.max_commute_km) : null,
      } as Partial<AvailabilityRead>);
      setAv(updated);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  }

  const auegColors = {
    green:  "border-green-200 bg-green-50 text-green-700",
    yellow: "border-yellow-200 bg-yellow-50 text-yellow-700",
    red:    "border-red-200 bg-red-50 text-red-700",
  };

  return (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-5 py-4 hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-lg">⏱</span>
          <span className="font-medium text-gray-900">Zeitarbeits-Verfügbarkeit</span>
          {av?.is_in_pool && (
            <span className="rounded-full bg-green-100 border border-green-200 px-2 py-0.5 text-xs text-green-700">
              Im Pool
            </span>
          )}
        </div>
        <span className="text-gray-400 text-sm">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="border-t border-gray-100 px-5 py-4 space-y-4">
          {/* AÜG status */}
          {av && (
            <div className={`rounded-lg border p-3 ${auegColors[av.aueg_status]}`}>
              <div className="flex items-center justify-between mb-1.5">
                <p className="text-xs font-semibold">AÜG-Überlassungsdauer</p>
                <span className="text-xs font-bold">
                  {Number(av.total_placed_months).toFixed(1)} / 18 Monate
                </span>
              </div>
              <div className="h-1.5 rounded-full bg-white/60 overflow-hidden">
                <div
                  className={`h-full rounded-full ${av.aueg_status === "red" ? "bg-red-500" : av.aueg_status === "yellow" ? "bg-yellow-400" : "bg-green-500"}`}
                  style={{ width: `${Math.min(100, (Number(av.total_placed_months) / 18) * 100)}%` }}
                />
              </div>
              <p className="text-xs mt-1">
                {av.aueg_status === "red"
                  ? "⚠ Höchstüberlassungsdauer erreicht"
                  : `Noch ${Number(av.aueg_remaining_months).toFixed(1)} Monate verfügbar`}
              </p>
            </div>
          )}

          {!editing ? (
            <>
              {av ? (
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <p className="text-xs text-gray-400">Im Pool</p>
                    <p className="font-medium mt-0.5">{av.is_in_pool ? "✓ Ja" : "Nein"}</p>
                  </div>
                  {av.available_from && (
                    <div>
                      <p className="text-xs text-gray-400">Verfügbar ab</p>
                      <p className="font-medium mt-0.5">{new Date(av.available_from).toLocaleDateString("de-DE")}</p>
                    </div>
                  )}
                  {av.preferred_location && (
                    <div>
                      <p className="text-xs text-gray-400">Wunschstandort</p>
                      <p className="font-medium mt-0.5">{av.preferred_location}</p>
                    </div>
                  )}
                  {av.preferred_shift && (
                    <div>
                      <p className="text-xs text-gray-400">Schicht</p>
                      <p className="font-medium mt-0.5">
                        {av.preferred_shift === "day" ? "Tagschicht" : av.preferred_shift === "night" ? "Nachtschicht" : "Flexibel"}
                      </p>
                    </div>
                  )}
                </div>
              ) : (
                <p className="text-sm text-gray-400">Noch keine Verfügbarkeit hinterlegt.</p>
              )}
              <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
                {av ? "Bearbeiten" : "Verfügbarkeit hinterlegen"}
              </Button>
            </>
          ) : (
            <div className="space-y-3">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input
                  type="checkbox"
                  checked={form.is_in_pool}
                  onChange={(e) => setForm({ ...form, is_in_pool: e.target.checked })}
                  className="rounded"
                />
                <span className="font-medium">Im Zeitarbeiter-Pool verfügbar</span>
              </label>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <Label htmlFor="av-from">Verfügbar ab</Label>
                  <Input id="av-from" type="date" value={form.available_from}
                    onChange={(e) => setForm({ ...form, available_from: e.target.value })} />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="av-until">Verfügbar bis</Label>
                  <Input id="av-until" type="date" value={form.available_until}
                    onChange={(e) => setForm({ ...form, available_until: e.target.value })} />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="av-shift">Bevorzugte Schicht</Label>
                  <select id="av-shift" value={form.preferred_shift}
                    onChange={(e) => setForm({ ...form, preferred_shift: e.target.value })}
                    className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                    <option value="day">Tagschicht</option>
                    <option value="night">Nachtschicht</option>
                    <option value="flexible">Flexibel</option>
                  </select>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="av-km">Max. Pendelweg (km)</Label>
                  <Input id="av-km" type="number" min="0" max="500" value={form.max_commute_km}
                    onChange={(e) => setForm({ ...form, max_commute_km: e.target.value })}
                    placeholder="50" />
                </div>
                <div className="space-y-1 col-span-2">
                  <Label htmlFor="av-loc">Wunschstandort</Label>
                  <Input id="av-loc" value={form.preferred_location}
                    onChange={(e) => setForm({ ...form, preferred_location: e.target.value })}
                    placeholder="München, Augsburg…" />
                </div>
              </div>

              <div className="flex gap-2">
                <Button size="sm" onClick={handleSave} disabled={saving}>
                  {saving ? "Wird gespeichert…" : "Speichern"}
                </Button>
                <Button size="sm" variant="outline" onClick={() => setEditing(false)}>
                  Abbrechen
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
