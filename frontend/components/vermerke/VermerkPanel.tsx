"use client";

import { useCallback, useEffect, useState } from "react";
import { auth } from "@/lib/auth";
import {
  vermerkeApi,
  type VermerkCreate,
  type VermerkRead,
  type VermerkType,
  type VermerkVisibility,
} from "@/lib/api";

const TYPE_LABELS: Record<VermerkType, string> = {
  präferenz: "Präferenz",
  warnhinweis: "Warnhinweis",
  beziehungswissen: "Beziehungswissen",
  dokumentenhinweis: "Dokumentenhinweis",
  override_grund: "Override-Grund",
};

const TYPE_COLORS: Record<VermerkType, string> = {
  präferenz: "bg-blue-50 text-blue-700 border-blue-200",
  warnhinweis: "bg-red-50 text-red-700 border-red-200",
  beziehungswissen: "bg-green-50 text-green-700 border-green-200",
  dokumentenhinweis: "bg-yellow-50 text-yellow-700 border-yellow-200",
  override_grund: "bg-purple-50 text-purple-700 border-purple-200",
};

interface Props {
  targetType: "candidate" | "application" | "assignment";
  targetId: string;
  /** Compact mode – only shows count badge, expands on click */
  compact?: boolean;
}

export function VermerkPanel({ targetType, targetId, compact = false }: Props) {
  const [vermerke, setVermerke] = useState<VermerkRead[]>([]);
  const [open, setOpen] = useState(!compact);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  // New vermerk form state
  const [formType, setFormType] = useState<VermerkType>("beziehungswissen");
  const [formText, setFormText] = useState("");
  const [formVisibility, setFormVisibility] = useState<VermerkVisibility>("internal");
  const [formStrength, setFormStrength] = useState<number | null>(null);

  const load = useCallback(async () => {
    const token = auth.getAccess();
    if (!token) return;
    setLoading(true);
    try {
      let result: VermerkRead[];
      if (targetType === "candidate") result = await vermerkeApi.listForCandidate(token, targetId);
      else if (targetType === "application") result = await vermerkeApi.listForApplication(token, targetId);
      else result = await vermerkeApi.listForAssignment(token, targetId);
      setVermerke(result);
    } catch {
      // silently fail – vermerke are optional context
    } finally {
      setLoading(false);
    }
  }, [targetType, targetId]);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!formText.trim()) return;
    const token = auth.getAccess();
    if (!token) return;

    const payload: VermerkCreate = {
      type: formType,
      text: formText.trim(),
      visibility: formVisibility,
      strength: formType === "warnhinweis" ? formStrength : null,
      [`${targetType}_id`]: targetId,
    };

    setSubmitting(true);
    try {
      const created = await vermerkeApi.create(token, payload);
      setVermerke((prev) => [created, ...prev]);
      setFormText("");
      setShowForm(false);
    } catch {
      alert("Vermerk konnte nicht gespeichert werden.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleDelete(id: string) {
    const token = auth.getAccess();
    if (!token) return;
    try {
      await vermerkeApi.delete(token, id);
      setVermerke((prev) => prev.filter((v) => v.id !== id));
    } catch {
      alert("Löschen fehlgeschlagen.");
    }
  }

  const activeCount = vermerke.length;

  if (compact && !open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-700 border border-gray-200 rounded px-2 py-0.5"
      >
        <span>Vermerke</span>
        {activeCount > 0 && (
          <span className="bg-amber-100 text-amber-700 rounded-full px-1.5 font-medium">
            {activeCount}
          </span>
        )}
      </button>
    );
  }

  return (
    <div className="rounded-lg border border-gray-100 bg-gray-50 p-3 space-y-2">
      {/* Header */}
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          Vermerke {activeCount > 0 && `(${activeCount})`}
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowForm((s) => !s)}
            className="text-xs text-blue-600 hover:text-blue-700 font-medium"
          >
            + Neu
          </button>
          {compact && (
            <button onClick={() => setOpen(false)} className="text-gray-400 hover:text-gray-600 text-sm leading-none">
              ×
            </button>
          )}
        </div>
      </div>

      {/* Add form */}
      {showForm && (
        <form onSubmit={handleSubmit} className="space-y-2 border border-gray-200 rounded p-2 bg-white">
          <div className="flex gap-2">
            <select
              value={formType}
              onChange={(e) => setFormType(e.target.value as VermerkType)}
              className="text-xs border border-gray-200 rounded px-2 py-1 flex-1"
            >
              {(Object.keys(TYPE_LABELS) as VermerkType[]).map((t) => (
                <option key={t} value={t}>{TYPE_LABELS[t]}</option>
              ))}
            </select>
            <select
              value={formVisibility}
              onChange={(e) => setFormVisibility(e.target.value as VermerkVisibility)}
              className="text-xs border border-gray-200 rounded px-2 py-1"
            >
              <option value="internal">Intern</option>
              <option value="partner">Partner</option>
              <option value="public">Öffentlich</option>
            </select>
          </div>

          {formType === "warnhinweis" && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-500">Stärke:</span>
              {[1, 2, 3, 4, 5].map((n) => (
                <button
                  key={n}
                  type="button"
                  onClick={() => setFormStrength(n)}
                  className={`w-5 h-5 rounded-full text-xs font-bold border ${
                    formStrength === n
                      ? "bg-red-500 text-white border-red-500"
                      : "border-gray-300 text-gray-400"
                  }`}
                >
                  {n}
                </button>
              ))}
            </div>
          )}

          <textarea
            value={formText}
            onChange={(e) => setFormText(e.target.value)}
            placeholder="Vermerk eingeben…"
            rows={2}
            className="w-full text-xs border border-gray-200 rounded px-2 py-1 resize-none"
            required
          />
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={submitting}
              className="text-xs bg-blue-600 text-white rounded px-3 py-1 hover:bg-blue-700 disabled:opacity-50"
            >
              {submitting ? "Speichere…" : "Speichern"}
            </button>
            <button
              type="button"
              onClick={() => setShowForm(false)}
              className="text-xs text-gray-500 hover:text-gray-700"
            >
              Abbrechen
            </button>
          </div>
        </form>
      )}

      {/* List */}
      {loading && <p className="text-xs text-gray-400">Lade…</p>}
      {!loading && vermerke.length === 0 && (
        <p className="text-xs text-gray-400 italic">Noch keine Vermerke.</p>
      )}
      <div className="space-y-1.5">
        {vermerke.map((v) => (
          <div key={v.id} className="bg-white rounded border border-gray-100 px-2.5 py-2 group">
            <div className="flex items-start justify-between gap-2">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 mb-1 flex-wrap">
                  <span className={`inline-flex items-center rounded-full border px-2 py-0 text-[10px] font-medium ${TYPE_COLORS[v.type as VermerkType]}`}>
                    {TYPE_LABELS[v.type as VermerkType] ?? v.type}
                  </span>
                  {v.type === "warnhinweis" && v.strength && (
                    <span className="flex gap-0.5">
                      {Array.from({ length: 5 }).map((_, i) => (
                        <span
                          key={i}
                          className={`w-1.5 h-1.5 rounded-full ${i < v.strength! ? "bg-red-500" : "bg-gray-200"}`}
                        />
                      ))}
                    </span>
                  )}
                  {v.visibility !== "internal" && (
                    <span className="text-[10px] text-gray-400">{v.visibility}</span>
                  )}
                </div>
                <p className="text-xs text-gray-700 leading-relaxed">{v.text}</p>
                <p className="text-[10px] text-gray-400 mt-1">
                  {new Date(v.created_at).toLocaleDateString("de-DE")}
                  {v.valid_until && ` · gültig bis ${new Date(v.valid_until).toLocaleDateString("de-DE")}`}
                </p>
              </div>
              <button
                onClick={() => handleDelete(v.id)}
                className="text-gray-300 hover:text-red-500 text-sm leading-none opacity-0 group-hover:opacity-100 transition-opacity shrink-0"
              >
                ×
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
