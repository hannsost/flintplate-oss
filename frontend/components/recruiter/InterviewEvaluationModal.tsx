"use client";

import { useEffect, useState } from "react";
import { auth } from "@/lib/auth";
import { scorecardApi, type ScorecardRead } from "@/lib/api";
import { Star, X } from "lucide-react";

const RECOMMENDATION_OPTIONS = [
  { value: "hire", label: "Einstellen", color: "border-green-500 bg-green-50 text-green-700" },
  { value: "maybe", label: "Eventuell", color: "border-yellow-400 bg-yellow-50 text-yellow-700" },
  { value: "no_hire", label: "Absagen", color: "border-red-400 bg-red-50 text-red-600" },
];

function StarRating({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number | null;
  onChange: (v: number) => void;
}) {
  const [hovered, setHovered] = useState<number | null>(null);
  const display = hovered ?? value ?? 0;

  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-sm text-gray-700">{label}</span>
      <div className="flex gap-1">
        {[1, 2, 3, 4, 5].map((star) => (
          <button
            key={star}
            type="button"
            onClick={() => onChange(star)}
            onMouseEnter={() => setHovered(star)}
            onMouseLeave={() => setHovered(null)}
            className="text-xl leading-none transition-colors"
          >
            <Star size={16} className={display >= star ? "text-yellow-400 fill-yellow-400" : "text-gray-200"} />
          </button>
        ))}
        {value && (
          <span className="ml-1 text-xs text-gray-400 self-center">{value}/5</span>
        )}
      </div>
    </div>
  );
}

interface Props {
  applicationId: string;
  candidateName: string | null;
  jobTitle?: string | null;
  onClose: () => void;
  onSaved?: (scorecard: ScorecardRead) => void;
}

export function InterviewEvaluationModal({
  applicationId,
  candidateName,
  jobTitle,
  onClose,
  onSaved,
}: Props) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [overallRating, setOverallRating] = useState<number | null>(null);
  const [technicalRating, setTechnicalRating] = useState<number | null>(null);
  const [communicationRating, setCommunicationRating] = useState<number | null>(null);
  const [motivationRating, setMotivationRating] = useState<number | null>(null);
  const [notes, setNotes] = useState("");
  const [recommendation, setRecommendation] = useState<string | null>(null);

  // Load existing scorecard
  useEffect(() => {
    const token = auth.getAccess();
    if (!token) return;
    scorecardApi.get(token, applicationId)
      .then((sc) => {
        if (sc) {
          setOverallRating(sc.overall_rating);
          setTechnicalRating(sc.technical_rating);
          setCommunicationRating(sc.communication_rating);
          setMotivationRating(sc.motivation_rating);
          setNotes(sc.notes ?? "");
          setRecommendation(sc.recommendation);
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [applicationId]);

  async function handleSave() {
    const token = auth.getAccess();
    if (!token) return;
    setSaving(true);
    setError(null);
    try {
      const sc = await scorecardApi.upsert(token, applicationId, {
        overall_rating: overallRating,
        technical_rating: technicalRating,
        communication_rating: communicationRating,
        motivation_rating: motivationRating,
        notes: notes.trim() || null,
        recommendation,
      });
      onSaved?.(sc);
      onClose();
    } catch {
      setError("Bewertung konnte nicht gespeichert werden.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-2xl bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-100 px-5 py-4">
          <div>
            <h2 className="font-bold text-gray-900">Interview-Bewertung</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {candidateName ?? "Kandidat"}
              {jobTitle && <span className="text-gray-400"> · {jobTitle}</span>}
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-full p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          >
            <X size={15} />
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
          </div>
        ) : (
          <div className="px-5 py-4 space-y-4">
            {/* Star ratings */}
            <div className="rounded-xl border border-gray-100 bg-gray-50 px-4 divide-y divide-gray-100">
              <StarRating label="Gesamteindruck" value={overallRating} onChange={setOverallRating} />
              <StarRating label="Fachliche Kompetenz" value={technicalRating} onChange={setTechnicalRating} />
              <StarRating label="Kommunikation" value={communicationRating} onChange={setCommunicationRating} />
              <StarRating label="Motivation / Fit" value={motivationRating} onChange={setMotivationRating} />
            </div>

            {/* Recommendation */}
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">Empfehlung</p>
              <div className="flex gap-2">
                {RECOMMENDATION_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setRecommendation(recommendation === opt.value ? null : opt.value)}
                    className={`flex-1 rounded-lg border-2 py-2 text-sm font-medium transition-colors ${
                      recommendation === opt.value
                        ? opt.color
                        : "border-gray-200 text-gray-600 hover:border-gray-300"
                    }`}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            {/* Notes */}
            <div>
              <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">Notizen</p>
              <textarea
                value={notes}
                onChange={(e) => setNotes(e.target.value)}
                rows={3}
                placeholder="Stärken, Schwächen, Besonderheiten…"
                className="w-full rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
              />
            </div>

            {error && <p className="text-sm text-red-500">{error}</p>}
          </div>
        )}

        {/* Footer */}
        <div className="flex justify-end gap-2 border-t border-gray-100 px-5 py-3">
          <button
            onClick={onClose}
            className="rounded-lg border border-gray-200 px-4 py-2 text-sm text-gray-600 hover:border-gray-300"
          >
            Abbrechen
          </button>
          <button
            onClick={handleSave}
            disabled={saving || loading}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {saving ? "Speichere…" : "Bewertung speichern"}
          </button>
        </div>
      </div>
    </div>
  );
}
