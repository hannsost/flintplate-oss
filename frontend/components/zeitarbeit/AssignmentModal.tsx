"use client";

import { useState } from "react";
import { auth } from "@/lib/auth";
import { zeitarbeitApi, ApiError, type AssignmentRead, type AssignmentCreate } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

interface Props {
  initial?: AssignmentRead;
  onClose: () => void;
  onSaved: (a: AssignmentRead) => void;
}

export function AssignmentModal({ initial, onClose, onSaved }: Props) {
  const [form, setForm] = useState<AssignmentCreate>({
    title: initial?.title ?? "",
    description: initial?.description ?? "",
    required_skills: initial?.required_skills ?? [],
    location: initial?.location ?? "",
    shift: initial?.shift ?? "flexible",
    hourly_rate: initial?.hourly_rate ?? null,
    start_date: initial?.start_date ?? null,
    end_date: initial?.end_date ?? null,
    max_duration_months: initial?.max_duration_months ?? 18,
    notes: initial?.notes ?? "",
  });
  const [skillsInput, setSkillsInput] = useState((initial?.required_skills ?? []).join(", "));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const token = auth.getAccess();
    if (!token) return;

    const payload: AssignmentCreate = {
      ...form,
      required_skills: skillsInput.split(",").map((s) => s.trim()).filter(Boolean),
    };

    setSaving(true);
    setError(null);
    try {
      let result: AssignmentRead;
      if (initial) {
        result = await zeitarbeitApi.updateAssignment(token, initial.id, payload);
      } else {
        result = await zeitarbeitApi.createAssignment(token, payload);
      }
      onSaved(result);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Fehler beim Speichern.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-lg rounded-xl bg-white shadow-xl overflow-y-auto max-h-[90vh]">
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4 sticky top-0 bg-white">
          <h2 className="font-semibold text-gray-900">
            {initial ? "Auftrag bearbeiten" : "Neuer Auftrag"}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl">×</button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {error && (
            <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">{error}</div>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="az-title">Titel *</Label>
            <Input
              id="az-title"
              required
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="z. B. Lagerhelfer (m/w/d)"
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="az-location">Einsatzort</Label>
              <Input
                id="az-location"
                value={form.location ?? ""}
                onChange={(e) => setForm({ ...form, location: e.target.value })}
                placeholder="München"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="az-shift">Schicht</Label>
              <select
                id="az-shift"
                value={form.shift ?? "flexible"}
                onChange={(e) => setForm({ ...form, shift: e.target.value })}
                className="w-full rounded-md border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="day">Tagschicht</option>
                <option value="night">Nachtschicht</option>
                <option value="flexible">Flexibel</option>
              </select>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="az-rate">Stundenlohn (€)</Label>
              <Input
                id="az-rate"
                type="number"
                step="0.50"
                min="0"
                value={form.hourly_rate ?? ""}
                onChange={(e) => setForm({ ...form, hourly_rate: e.target.value ? parseFloat(e.target.value) : null })}
                placeholder="14.50"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="az-maxdur">Max. Einsatzdauer (Monate)</Label>
              <Input
                id="az-maxdur"
                type="number"
                min="1"
                max="18"
                value={form.max_duration_months}
                onChange={(e) => setForm({ ...form, max_duration_months: parseInt(e.target.value) })}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="az-start">Beginn</Label>
              <Input
                id="az-start"
                type="date"
                value={form.start_date ?? ""}
                onChange={(e) => setForm({ ...form, start_date: e.target.value || null })}
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="az-end">Ende</Label>
              <Input
                id="az-end"
                type="date"
                value={form.end_date ?? ""}
                onChange={(e) => setForm({ ...form, end_date: e.target.value || null })}
              />
            </div>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="az-skills">Benötigte Skills (kommagetrennt)</Label>
            <Input
              id="az-skills"
              value={skillsInput}
              onChange={(e) => setSkillsInput(e.target.value)}
              placeholder="Gabelstapler, Lagerhaltung, MS Office"
            />
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="az-desc">Beschreibung</Label>
            <Textarea
              id="az-desc"
              rows={3}
              value={form.description ?? ""}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
              placeholder="Aufgaben, Anforderungen, Besonderheiten…"
            />
          </div>

          <div className="flex justify-end gap-3 pt-1">
            <Button type="button" variant="outline" onClick={onClose}>Abbrechen</Button>
            <Button type="submit" disabled={saving}>
              {saving ? "Wird gespeichert…" : initial ? "Speichern" : "Anlegen"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
