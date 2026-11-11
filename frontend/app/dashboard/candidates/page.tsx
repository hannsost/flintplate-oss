"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";
import { recruiterApi, workerManagementApi, type CandidateSearchResult } from "@/lib/api";
import { CandidateProfileModal } from "@/components/recruiter/CandidateProfileModal";
import { UserCheck } from "lucide-react";

export default function CandidateSearchPage() {
  const router = useRouter();
  const [candidates, setCandidates] = useState<CandidateSearchResult[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");
  const [location, setLocation] = useState("");
  const [skillInput, setSkillInput] = useState("");
  const [skills, setSkills] = useState<string[]>([]);
  const [availableOnly, setAvailableOnly] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Profile modal
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [selectedName, setSelectedName] = useState<string | null>(null);

  // Quick-activate state: tracks which user is being activated inline
  const [activatingId, setActivatingId] = useState<string | null>(null);
  // Set of already-activated user IDs (so we can show the badge in the row)
  const [activatedIds, setActivatedIds] = useState<Set<string>>(new Set());

  const PAGE_SIZE = 20;

  const search = useCallback(
    (p = 1) => {
      const token = auth.getAccess();
      if (!token) { router.push("/login"); return; }
      setLoading(true);
      setError(null);
      recruiterApi
        .searchCandidates(token, {
          query: query.trim() || undefined,
          location: location.trim() || undefined,
          skills: skills.length ? skills : undefined,
          available_only: availableOnly || undefined,
          page: p,
          page_size: PAGE_SIZE,
        })
        .then((res) => {
          setCandidates(res.candidates);
          setTotal(res.total);
          setPage(p);
        })
        .catch(() => setError("Fehler bei der Suche."))
        .finally(() => setLoading(false));
    },
    [query, location, skills, availableOnly, router],
  );

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) { router.push("/login"); return; }
    search(1);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function addSkill() {
    const s = skillInput.trim().toLowerCase();
    if (s && !skills.includes(s)) setSkills((prev) => [...prev, s]);
    setSkillInput("");
  }

  async function handleQuickActivate(userId: string) {
    const token = auth.getAccess();
    if (!token) return;
    setActivatingId(userId);
    try {
      await workerManagementApi.activate(token, {
        user_id: userId,
        employment_type: "temp",
      });
      setActivatedIds((prev) => new Set([...prev, userId]));
    } catch {
      // If already activated, still mark as done
      setActivatedIds((prev) => new Set([...prev, userId]));
    } finally {
      setActivatingId(null);
    }
  }

  function handleActivatedFromModal(userId: string) {
    setActivatedIds((prev) => new Set([...prev, userId]));
    setSelectedUserId(null);
    setSelectedName(null);
  }

  const totalPages = Math.ceil(total / PAGE_SIZE);

  return (
    <div className="min-h-screen bg-gray-50">

      <main className="mx-auto max-w-5xl px-4 py-8 space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Kandidaten-Suche</h1>
            <p className="mt-1 text-sm text-gray-500">Durchsuche alle registrierten Kandidaten</p>
          </div>
          <span className="text-sm text-gray-500">{total} Treffer</span>
        </div>

        {/* Search form */}
        <div className="rounded-2xl border border-gray-200 bg-white shadow-sm p-4 space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <input
              type="text"
              placeholder="Name, Headline, Ort…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && search(1)}
              className="rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <input
              type="text"
              placeholder="Ort"
              value={location}
              onChange={(e) => setLocation(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && search(1)}
              className="rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="Skill hinzufügen…"
                value={skillInput}
                onChange={(e) => setSkillInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addSkill(); } }}
                className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <button
                onClick={addSkill}
                className="rounded-lg border border-gray-200 px-3 py-2 text-sm text-gray-600 hover:border-gray-400"
              >
                +
              </button>
            </div>
          </div>

          {/* Active skill tags */}
          {skills.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {skills.map((s) => (
                <span
                  key={s}
                  className="inline-flex items-center gap-1 rounded-full bg-blue-50 border border-blue-200 px-2.5 py-0.5 text-xs text-blue-700"
                >
                  {s}
                  <button
                    onClick={() => setSkills((prev) => prev.filter((x) => x !== s))}
                    className="hover:text-blue-900 ml-0.5"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}

          <div className="flex items-center justify-between">
            <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer">
              <input
                type="checkbox"
                checked={availableOnly}
                onChange={(e) => setAvailableOnly(e.target.checked)}
                className="rounded"
              />
              Nur Pool-Kandidaten (Zeitarbeit)
            </label>
            <button
              onClick={() => search(1)}
              disabled={loading}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {loading ? "Suche…" : "Suchen"}
            </button>
          </div>
        </div>

        {/* Results */}
        <div className="rounded-2xl border border-gray-200 bg-white shadow-sm overflow-hidden">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
            </div>
          ) : error ? (
            <div className="py-16 text-center text-sm text-red-500">{error}</div>
          ) : candidates.length === 0 ? (
            <div className="py-16 text-center text-sm text-gray-400">Keine Kandidaten gefunden.</div>
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b border-gray-200 bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Name</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Headline</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Ort</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Profil</th>
                  <th className="px-4 py-3 text-left font-medium text-gray-500">Aktionen</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {candidates.map((c) => {
                  const isActivated = activatedIds.has(c.user_id);
                  return (
                    <tr key={c.user_id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <p className="font-medium text-gray-900">{c.full_name ?? "—"}</p>
                          {isActivated && (
                            <span className="inline-flex items-center gap-0.5 rounded-full bg-blue-50 border border-blue-200 px-1.5 py-0.5 text-[10px] font-medium text-blue-700">
                              <UserCheck size={9} />
                              Worker
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3 text-gray-600 max-w-[220px] truncate">
                        {c.headline ?? "—"}
                      </td>
                      <td className="px-4 py-3 text-gray-500">{c.location ?? "—"}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-16 rounded-full bg-gray-200">
                            <div
                              className="h-1.5 rounded-full bg-blue-500"
                              style={{ width: `${c.completeness_score}%` }}
                            />
                          </div>
                          <span className="text-xs text-gray-400">{c.completeness_score}%</span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => { setSelectedUserId(c.user_id); setSelectedName(c.full_name); }}
                            className="rounded border border-blue-200 bg-blue-50 px-2 py-0.5 text-xs text-blue-700 hover:bg-blue-100 transition-colors"
                          >
                            Profil ansehen
                          </button>
                          {!isActivated && (
                            <button
                              onClick={() => handleQuickActivate(c.user_id)}
                              disabled={activatingId === c.user_id}
                              className="flex items-center gap-1 rounded border border-blue-200 bg-blue-50 px-2 py-0.5 text-xs text-blue-700 hover:bg-blue-100 disabled:opacity-50 transition-colors"
                            >
                              <UserCheck size={10} />
                              {activatingId === c.user_id ? "…" : "Als Worker"}
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-2">
            <button
              onClick={() => search(page - 1)}
              disabled={page === 1 || loading}
              className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:border-gray-300 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              ← Zurück
            </button>
            <span className="text-sm text-gray-500">Seite {page} von {totalPages}</span>
            <button
              onClick={() => search(page + 1)}
              disabled={page === totalPages || loading}
              className="rounded-lg border border-gray-200 px-3 py-1.5 text-sm text-gray-600 hover:border-gray-300 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Weiter →
            </button>
          </div>
        )}
      </main>

      {selectedUserId && (
        <CandidateProfileModal
          userId={selectedUserId}
          candidateName={selectedName}
          onClose={() => { setSelectedUserId(null); setSelectedName(null); }}
          onActivated={handleActivatedFromModal}
        />
      )}
    </div>
  );
}
