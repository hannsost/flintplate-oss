"use client";

import { useEffect, useState } from "react";
import { auth } from "@/lib/auth";
import { marketApi } from "@/lib/api";
import type { ProfileGapAnalysis, SkillGap, LearningPath } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const DIFFICULTY_CONFIG = {
  beginner:     { label: "Einsteiger",    color: "bg-green-100 text-green-700 border-green-200" },
  intermediate: { label: "Fortgeschritten", color: "bg-yellow-100 text-yellow-700 border-yellow-200" },
  advanced:     { label: "Experte",       color: "bg-red-100 text-red-600 border-red-200" },
};

function GapRow({ gap }: { gap: SkillGap }) {
  const diff = DIFFICULTY_CONFIG[gap.difficulty as keyof typeof DIFFICULTY_CONFIG];
  return (
    <div className="flex items-center justify-between gap-3 py-2 border-b border-gray-100 last:border-0">
      <div className="flex items-center gap-2 min-w-0">
        <span className="w-2 h-2 rounded-full bg-red-400 shrink-0" />
        <span className="text-sm font-medium text-gray-800 capitalize">{gap.skill}</span>
        {diff && (
          <span className={`rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${diff.color}`}>
            {diff.label}
          </span>
        )}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {gap.est_hours && (
          <span className="text-[10px] text-gray-400">~{gap.est_hours}h</span>
        )}
        <span className="text-xs text-gray-400">{gap.market_demand_pct}%</span>
        {gap.course_url && (
          <a
            href={gap.course_url}
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-full bg-blue-50 border border-blue-200 px-2 py-0.5 text-xs text-blue-600 hover:bg-blue-100 transition-colors"
          >
            Kurs →
          </a>
        )}
      </div>
    </div>
  );
}

function LearningPathCard({ path }: { path: LearningPath }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="rounded-lg border border-gray-200 overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
      >
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-gray-800">{path.category}</span>
          <span className="text-xs text-gray-500">{path.skills.length} Skills</span>
          <span className="text-xs text-gray-400">~{path.total_hours}h gesamt</span>
        </div>
        <span className="text-gray-400 text-xs">{expanded ? "▲" : "▼"}</span>
      </button>
      {expanded && (
        <div className="px-4 pb-1">
          {path.skills.map((g) => <GapRow key={g.skill} gap={g} />)}
        </div>
      )}
    </div>
  );
}

export function SkillGapWidget() {
  const [data, setData] = useState<ProfileGapAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"gaps" | "paths">("paths");

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) return;
    marketApi.myGaps(token).then(setData).catch(() => {}).finally(() => setLoading(false));
  }, []);

  if (loading || !data) return null;
  if (data.top_gaps.length === 0 && data.strong_skills.length === 0) return null;

  const coverageColor =
    data.coverage_pct >= 70 ? "text-green-600" :
    data.coverage_pct >= 40 ? "text-yellow-600" : "text-red-500";

  const barColor =
    data.coverage_pct >= 70 ? "bg-green-500" :
    data.coverage_pct >= 40 ? "bg-yellow-400" : "bg-red-400";

  return (
    <Card>
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base">Skills-Gap Analyse v2</CardTitle>
          <button onClick={() => setOpen((o) => !o)} className="text-xs text-gray-500 hover:text-gray-700">
            {open ? "▲ Einklappen" : "▼ Ausklappen"}
          </button>
        </div>
        <p className="text-xs text-gray-500 mt-0.5">
          Du deckst{" "}
          <span className={`font-semibold ${coverageColor}`}>{data.coverage_pct}%</span>{" "}
          der Top-50 Markt-Skills ab.
        </p>
      </CardHeader>

      {open && (
        <CardContent className="space-y-4">
          {/* Coverage bar */}
          <div>
            <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
              <span>Marktabdeckung</span>
              <span>{data.coverage_pct}%</span>
            </div>
            <div className="h-2 rounded-full bg-gray-100 overflow-hidden">
              <div className={`h-full rounded-full transition-all duration-700 ${barColor}`}
                style={{ width: `${data.coverage_pct}%` }} />
            </div>
          </div>

          {/* Strong skills */}
          {data.strong_skills.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-600 mb-2">Deine Stärken</p>
              <div className="flex flex-wrap gap-1.5">
                {data.strong_skills.map((s) => (
                  <span key={s} className="rounded-full bg-green-50 border border-green-200 px-2 py-0.5 text-xs text-green-700 font-medium capitalize">
                    ✓ {s}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* View toggle */}
          {data.learning_paths.length > 0 && (
            <div className="flex gap-1 rounded-lg border border-gray-200 bg-gray-50 p-1 w-fit">
              {(["paths", "gaps"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                    view === v ? "bg-white shadow-sm text-gray-900" : "text-gray-500 hover:text-gray-700"
                  }`}
                >
                  {v === "paths" ? "📚 Learning Paths" : "📋 Alle Gaps"}
                </button>
              ))}
            </div>
          )}

          {/* Learning paths view */}
          {view === "paths" && data.learning_paths.length > 0 && (
            <div className="space-y-2">
              {data.learning_paths.map((p) => (
                <LearningPathCard key={p.category} path={p} />
              ))}
            </div>
          )}

          {/* Flat gaps view */}
          {view === "gaps" && data.top_gaps.length > 0 && (
            <div>
              <p className="text-xs font-medium text-gray-600 mb-1">
                Fehlende Skills ({data.top_gaps.length} identifiziert)
              </p>
              {data.top_gaps.slice(0, 12).map((g) => <GapRow key={g.skill} gap={g} />)}
              {data.top_gaps.length > 12 && (
                <p className="text-xs text-gray-400 pt-2 text-center">+ {data.top_gaps.length - 12} weitere</p>
              )}
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
