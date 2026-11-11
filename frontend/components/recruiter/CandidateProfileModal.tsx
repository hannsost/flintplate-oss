"use client";

import { useEffect, useState } from "react";
import { auth } from "@/lib/auth";
import { recruiterApi, workerManagementApi } from "@/lib/api";
import type { CandidateProfileFull } from "@/lib/api";
import { X, MapPin, Mail, Phone, UserCheck, ChevronDown } from "lucide-react";

interface Props {
  userId: string;
  candidateName: string | null;
  onClose: () => void;
  /** Called after successful activation so the parent can refresh its list. */
  onActivated?: (userId: string) => void;
}

const EMPLOYMENT_TYPES = [
  { value: "temp",      label: "Zeitarbeit (temp)" },
  { value: "fulltime",  label: "Vollzeit" },
  { value: "parttime",  label: "Teilzeit" },
  { value: "minijob",   label: "Minijob" },
];

function formatDate(d: string | null): string {
  if (!d) return "";
  const [y, m] = d.split("-");
  return m ? `${m}/${y}` : y;
}

export function CandidateProfileModal({ userId, candidateName, onClose, onActivated }: Props) {
  const [profile, setProfile] = useState<CandidateProfileFull | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Activation panel state
  const [activating, setActivating] = useState(false);
  const [activateOpen, setActivateOpen] = useState(false);
  const [employmentType, setEmploymentType] = useState("temp");
  const [hourlyRate, setHourlyRate] = useState("");
  const [activateError, setActivateError] = useState<string | null>(null);
  const [activated, setActivated] = useState(false);

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) return;
    recruiterApi.getCandidateProfile(token, userId)
      .then(setProfile)
      .catch(() => setError("Profil konnte nicht geladen werden."))
      .finally(() => setLoading(false));
  }, [userId]);

  async function handleActivate() {
    const token = auth.getAccess();
    if (!token) return;
    setActivating(true);
    setActivateError(null);
    try {
      await workerManagementApi.activate(token, {
        user_id: userId,
        employment_type: employmentType,
        hourly_rate: hourlyRate ? parseFloat(hourlyRate) : undefined,
      });
      setActivated(true);
      setActivateOpen(false);
      onActivated?.(userId);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Aktivierung fehlgeschlagen.";
      setActivateError(msg);
    } finally {
      setActivating(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onClose}>
      <div
        className="relative w-full max-w-2xl max-h-[85vh] overflow-y-auto rounded-2xl bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="sticky top-0 z-10 flex items-center justify-between bg-white px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-bold text-gray-900">{candidateName ?? "Kandidaten-Profil"}</h2>
            {activated && (
              <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 border border-blue-200 px-2.5 py-0.5 text-xs font-medium text-blue-700">
                <UserCheck size={11} />
                Als Worker aktiviert
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {!activated && (
              <button
                onClick={() => setActivateOpen((v) => !v)}
                className="flex items-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-100 transition-colors"
              >
                <UserCheck size={13} />
                Als Zeitarbeiter aktivieren
                <ChevronDown size={11} className={`transition-transform ${activateOpen ? "rotate-180" : ""}`} />
              </button>
            )}
            <button
              onClick={onClose}
              className="rounded-full p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600 transition-colors"
            >
              <X size={15} />
            </button>
          </div>
        </div>

        {/* Activation panel */}
        {activateOpen && !activated && (
          <div className="border-b border-blue-100 bg-blue-50/60 px-6 py-4">
            <p className="text-xs font-semibold text-blue-800 mb-3">
              {candidateName} als Zeitarbeiter aufnehmen
            </p>
            <div className="flex flex-wrap items-end gap-3">
              <div>
                <label className="block text-xs text-gray-600 mb-1">Beschäftigungsart</label>
                <select
                  value={employmentType}
                  onChange={(e) => setEmploymentType(e.target.value)}
                  className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {EMPLOYMENT_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>{t.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-600 mb-1">Stundenlohn (brutto, €)</label>
                <input
                  type="number"
                  step="0.10"
                  min="12"
                  placeholder="z.B. 15.50"
                  value={hourlyRate}
                  onChange={(e) => setHourlyRate(e.target.value)}
                  className="w-32 rounded-lg border border-gray-200 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <button
                onClick={handleActivate}
                disabled={activating}
                className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {activating ? "Aktiviere…" : "Jetzt aktivieren"}
              </button>
            </div>
            {activateError && (
              <p className="mt-2 text-xs text-red-600">{activateError}</p>
            )}
          </div>
        )}

        <div className="px-6 py-5 space-y-6">
          {loading && (
            <div className="flex justify-center py-12">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
            </div>
          )}

          {error && <p className="text-center text-red-500">{error}</p>}

          {profile && (
            <>
              {/* Contact info */}
              <div className="space-y-1">
                {profile.headline && (
                  <p className="text-sm font-medium text-gray-700">{profile.headline}</p>
                )}
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-gray-500">
                  {profile.location && <span className="flex items-center gap-1"><MapPin size={11} className="text-gray-400" />{profile.location}</span>}
                  {profile.email && <span className="flex items-center gap-1"><Mail size={11} className="text-gray-400" />{profile.email}</span>}
                  {profile.phone && <span className="flex items-center gap-1"><Phone size={11} className="text-gray-400" />{profile.phone}</span>}
                  {profile.linkedin_url && (
                    <a
                      href={profile.linkedin_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-600 hover:underline"
                    >
                      LinkedIn
                    </a>
                  )}
                </div>
                <div className="mt-1">
                  <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-600">
                    Profil {profile.completeness_score}% vollständig
                  </span>
                </div>
              </div>

              {/* Summary */}
              {profile.summary && (
                <div>
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-2">Zusammenfassung</h3>
                  <p className="text-sm text-gray-700 leading-relaxed">{profile.summary}</p>
                </div>
              )}

              {/* Work experience */}
              {profile.work_experiences.length > 0 && (
                <div>
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">Berufserfahrung</h3>
                  <div className="space-y-3">
                    {profile.work_experiences.map((w, i) => (
                      <div key={i} className="flex gap-3">
                        <div className="mt-1 h-2 w-2 shrink-0 rounded-full bg-blue-400" />
                        <div className="min-w-0">
                          <p className="font-medium text-sm text-gray-900">{w.title}</p>
                          <p className="text-sm text-gray-600">{w.company}</p>
                          <p className="text-xs text-gray-400">
                            {formatDate(w.start_date)}
                            {w.start_date && " – "}
                            {w.is_current ? "heute" : formatDate(w.end_date)}
                          </p>
                          {w.description && (
                            <p className="text-xs text-gray-500 mt-1 leading-relaxed">{w.description}</p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Education */}
              {profile.educations.length > 0 && (
                <div>
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">Ausbildung</h3>
                  <div className="space-y-3">
                    {profile.educations.map((e, i) => (
                      <div key={i} className="flex gap-3">
                        <div className="mt-1 h-2 w-2 shrink-0 rounded-full bg-purple-400" />
                        <div>
                          <p className="font-medium text-sm text-gray-900">
                            {[e.degree, e.field_of_study].filter(Boolean).join(", ") || "Abschluss"}
                          </p>
                          <p className="text-sm text-gray-600">{e.institution}</p>
                          {(e.start_date || e.end_date) && (
                            <p className="text-xs text-gray-400">
                              {formatDate(e.start_date)}{e.start_date && e.end_date && " – "}{formatDate(e.end_date)}
                            </p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Skills */}
              {profile.skills.length > 0 && (
                <div>
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-gray-400 mb-3">Skills</h3>
                  <div className="flex flex-wrap gap-2">
                    {profile.skills.map((s, i) => (
                      <span
                        key={i}
                        className="rounded-full bg-gray-100 px-3 py-0.5 text-xs text-gray-700"
                        title={s.level ?? undefined}
                      >
                        {s.name}
                        {s.level && <span className="ml-1 text-gray-400">· {s.level}</span>}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
