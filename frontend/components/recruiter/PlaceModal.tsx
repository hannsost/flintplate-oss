"use client";

import { useState } from "react";
import { auth } from "@/lib/auth";
import { placementApi, ApiError, type PlacementRead } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";

interface Props {
  applicationId: string;
  candidateName: string | null;
  onClose: () => void;
  onSuccess: (placement: PlacementRead) => void;
}

export function PlaceModal({ applicationId, candidateName, onClose, onSuccess }: Props) {
  const [commissionPct, setCommissionPct] = useState("27.50");
  const [annualSalary, setAnnualSalary] = useState("");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const computedCommission =
    annualSalary && commissionPct
      ? ((parseFloat(annualSalary) * parseFloat(commissionPct)) / 100).toLocaleString("de-DE", {
          style: "currency",
          currency: "EUR",
          maximumFractionDigits: 0,
        })
      : null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const token = auth.getAccess();
    if (!token) return;
    setLoading(true);
    setError(null);
    try {
      const placement = await placementApi.place(token, applicationId, {
        commission_pct: parseFloat(commissionPct),
        annual_salary: annualSalary ? parseInt(annualSalary, 10) : null,
        notes: notes.trim() || null,
      });
      onSuccess(placement);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Fehler beim Erfassen.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-md rounded-xl bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <h2 className="font-semibold text-gray-900">Kandidat platzieren</h2>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">×</button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4">
          {candidateName && (
            <p className="text-sm text-gray-600">
              Kandidat: <span className="font-medium">{candidateName}</span>
            </p>
          )}

          {error && (
            <div className="rounded-lg bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="pct">Provisionssatz (%)</Label>
              <Input
                id="pct"
                type="number"
                step="0.5"
                min="0"
                max="100"
                value={commissionPct}
                onChange={(e) => setCommissionPct(e.target.value)}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="salary">Jahresgehalt (€, optional)</Label>
              <Input
                id="salary"
                type="number"
                min="0"
                step="1000"
                value={annualSalary}
                onChange={(e) => setAnnualSalary(e.target.value)}
                placeholder="z. B. 65000"
              />
            </div>
          </div>

          {computedCommission && (
            <div className="rounded-lg bg-green-50 border border-green-200 px-4 py-3">
              <p className="text-xs text-green-600 font-medium">Berechnete Provision</p>
              <p className="text-xl font-bold text-green-700 mt-0.5">{computedCommission}</p>
            </div>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="place-notes">Notizen (optional)</Label>
            <Textarea
              id="place-notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              placeholder="Interne Anmerkungen zum Placement…"
            />
          </div>

          <div className="flex justify-end gap-3 pt-1">
            <Button type="button" variant="outline" onClick={onClose}>
              Abbrechen
            </Button>
            <Button type="submit" disabled={loading} className="bg-green-600 hover:bg-green-700 text-white">
              {loading ? "Wird gespeichert…" : "✓ Als platziert erfassen"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
