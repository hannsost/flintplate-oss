"use client";

import { useState, useEffect } from "react";
import { auth } from "@/lib/auth";
import { interviewApi, ApiError, type InterviewPrepResponse, type InterviewQuestion } from "@/lib/api";
import { Navbar } from "@/components/layout/Navbar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { ModuleUpgradeHint } from "@/components/ui/ModuleGate";
import { fetchModules, MODULE_KEYS } from "@/lib/modules";

// ── Category badge ─────────────────────────────────────────────────────────

const CATEGORY_CONFIG: Record<string, { label: string; color: string }> = {
  technical:  { label: "Fachlich",     color: "bg-blue-50 text-blue-700 border-blue-200" },
  behavioral: { label: "Behavioral",   color: "bg-purple-50 text-purple-700 border-purple-200" },
  company:    { label: "Unternehmen",  color: "bg-amber-50 text-amber-700 border-amber-200" },
  motivation: { label: "Motivation",   color: "bg-green-50 text-green-700 border-green-200" },
  general:    { label: "Allgemein",    color: "bg-gray-50 text-gray-700 border-gray-200" },
};

function CategoryBadge({ category }: { category: string }) {
  const cfg = CATEGORY_CONFIG[category] ?? CATEGORY_CONFIG.general;
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded border ${cfg.color}`}>
      {cfg.label}
    </span>
  );
}

// ── Question card ──────────────────────────────────────────────────────────

function QuestionCard({ q, index }: { q: InterviewQuestion; index: number }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
      <button
        className="w-full text-left px-4 py-3 flex items-start gap-3 hover:bg-gray-50 transition-colors"
        onClick={() => setOpen(!open)}
      >
        <span className="shrink-0 w-6 h-6 rounded-full bg-blue-100 text-blue-700 text-xs font-bold flex items-center justify-center mt-0.5">
          {index + 1}
        </span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <CategoryBadge category={q.category} />
            {q.category === "behavioral" && (
              <span className="text-xs text-purple-500 font-medium">⭐ STAR</span>
            )}
          </div>
          <p className="text-sm font-medium text-gray-800">{q.question}</p>
        </div>
        <span className="shrink-0 text-gray-400 text-sm">{open ? "▲" : "▼"}</span>
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-3 border-t border-gray-100 pt-3">
          {q.star_tip && (
            <div className="rounded-lg bg-purple-50 border border-purple-100 p-3">
              <p className="text-xs font-semibold text-purple-700 mb-1">STAR-Methode</p>
              <p className="text-sm text-purple-800">{q.star_tip}</p>
            </div>
          )}
          {q.example_answer_hint && (
            <div className="rounded-lg bg-blue-50 border border-blue-100 p-3">
              <p className="text-xs font-semibold text-blue-700 mb-1">Hinweis für gute Antwort</p>
              <p className="text-sm text-blue-800">{q.example_answer_hint}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────

export default function InterviewPrepPage() {
  const [company, setCompany] = useState("");
  const [position, setPosition] = useState("");
  const [jobDesc, setJobDesc] = useState("");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<InterviewPrepResponse | null>(null);
  const [filterCategory, setFilterCategory] = useState<string>("all");
  const [modules, setModules] = useState<string[] | null>(null);

  useEffect(() => {
    const token = auth.getAccess();
    if (token) fetchModules(token).then(setModules);
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const token = auth.getAccess();
    if (!token) return;
    setGenerating(true);
    setError(null);
    try {
      const prep = await interviewApi.generate(token, {
        company,
        position,
        job_description: jobDesc || null,
      });
      setResult(prep);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Fehler bei der Generierung.");
    } finally {
      setGenerating(false);
    }
  }

  const categories = result
    ? ["all", ...Array.from(new Set(result.questions.map((q) => q.category)))]
    : [];

  const filtered = result
    ? filterCategory === "all"
      ? result.questions
      : result.questions.filter((q) => q.category === filterCategory)
    : [];

  if (modules !== null && !modules.includes(MODULE_KEYS.AI_INTERVIEW_PREP)) {
    return (
      <>
        <Navbar />
        <div className="max-w-2xl mx-auto px-4 py-16">
          <ModuleUpgradeHint name="KI Interview-Vorbereitung" category="ai" />
        </div>
      </>
    );
  }

  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-3xl px-4 py-8">
        <div className="mb-6">
          <h1 className="text-xl font-bold text-gray-900">Interview-Vorbereitung</h1>
          <p className="text-sm text-gray-400 mt-0.5">KI-generierte Fragen + STAR-Methoden-Coach</p>
        </div>

        {!result ? (
          <form onSubmit={handleSubmit} className="space-y-4 rounded-xl border border-gray-200 bg-white p-5">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label htmlFor="ip-company">Unternehmen *</Label>
                <Input
                  id="ip-company"
                  required
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                  placeholder="Acme GmbH"
                />
              </div>
              <div>
                <Label htmlFor="ip-position">Stelle *</Label>
                <Input
                  id="ip-position"
                  required
                  value={position}
                  onChange={(e) => setPosition(e.target.value)}
                  placeholder="Senior Backend Engineer"
                />
              </div>
            </div>
            <div>
              <Label htmlFor="ip-desc">Stellenbeschreibung (empfohlen)</Label>
              <Textarea
                id="ip-desc"
                value={jobDesc}
                onChange={(e) => setJobDesc(e.target.value)}
                rows={5}
                placeholder="Füge die Stellenbeschreibung ein für präzisere Fragen…"
              />
            </div>
            {error && <p className="text-sm text-red-600">{error}</p>}
            <Button type="submit" disabled={generating} className="w-full">
              {generating ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  Generiere Interviewfragen…
                </span>
              ) : "🎯 Interview-Vorbereitung starten"}
            </Button>
          </form>
        ) : (
          <div className="space-y-4">
            {/* Header */}
            <div className="flex items-center justify-between">
              <div>
                <p className="font-semibold text-gray-900">{position} bei {company}</p>
                <p className="text-xs text-gray-400 mt-0.5">
                  {result.questions.length} Fragen · {result.model_used}
                </p>
              </div>
              <Button variant="outline" size="sm" onClick={() => setResult(null)}>
                Neu generieren
              </Button>
            </div>

            {/* AI disclaimer */}
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-700">
              ⚠️ {result.disclaimer}
            </div>

            {/* Category filter */}
            <div className="flex gap-2 flex-wrap">
              {categories.map((cat) => (
                <button
                  key={cat}
                  onClick={() => setFilterCategory(cat)}
                  className={`text-xs px-3 py-1.5 rounded-full border transition-colors ${
                    filterCategory === cat
                      ? "bg-blue-600 text-white border-blue-600"
                      : "border-gray-200 text-gray-600 hover:border-gray-300"
                  }`}
                >
                  {cat === "all" ? `Alle (${result.questions.length})` : (CATEGORY_CONFIG[cat]?.label ?? cat)}
                </button>
              ))}
            </div>

            {/* Questions */}
            <div className="space-y-2">
              {filtered.map((q, i) => (
                <QuestionCard key={i} q={q} index={i} />
              ))}
            </div>

            {/* General tips */}
            {result.general_tips.length > 0 && (
              <div className="rounded-xl border border-green-200 bg-green-50 p-4">
                <p className="text-sm font-semibold text-green-800 mb-2">💡 Allgemeine Tipps</p>
                <ul className="space-y-1">
                  {result.general_tips.map((tip, i) => (
                    <li key={i} className="text-sm text-green-700 flex gap-2">
                      <span className="shrink-0">•</span>
                      <span>{tip}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </main>
    </>
  );
}
