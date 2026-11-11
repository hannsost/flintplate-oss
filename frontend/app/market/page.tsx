"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";
import { marketApi, ApiError } from "@/lib/api";
import type { MarketStats } from "@/lib/api";
import { Navbar } from "@/components/layout/Navbar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { SkillGapWidget } from "@/components/profile/SkillGapWidget";

// ── Helpers ────────────────────────────────────────────────────────────────

function fmt(n: number) {
  return `${Math.round(n / 1000)}k`;
}

// ── Bar ────────────────────────────────────────────────────────────────────

function HBar({
  label,
  value,
  max,
  pct,
  color = "bg-blue-500",
}: {
  label: string;
  value: number;
  max: number;
  pct: number;
  color?: string;
}) {
  const w = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="w-40 truncate text-sm text-gray-700 text-right shrink-0">{label}</span>
      <div className="flex-1 h-5 rounded bg-gray-100 overflow-hidden">
        <div
          className={`h-full rounded ${color} transition-all duration-500`}
          style={{ width: `${w}%` }}
        />
      </div>
      <span className="w-14 text-xs text-gray-500 shrink-0">{value} ({pct}%)</span>
    </div>
  );
}

// ── Salary card ────────────────────────────────────────────────────────────

function SalaryBar({
  category,
  min,
  max,
  mid,
}: {
  category: string;
  min: number | null;
  max: number | null;
  mid: number | null;
}) {
  const midVal = mid ?? ((min ?? 0) + (max ?? 0)) / 2;
  const scaleMax = 150000;
  const leftPct = min ? Math.round((min / scaleMax) * 100) : 0;
  const rightPct = max ? Math.round((max / scaleMax) * 100) : leftPct + 5;
  const width = Math.max(rightPct - leftPct, 3);

  return (
    <div className="flex items-center gap-3">
      <span className="w-36 truncate text-sm text-gray-700 text-right shrink-0">{category}</span>
      <div className="flex-1 relative h-5 rounded bg-gray-100 overflow-hidden">
        <div
          className="absolute h-full rounded bg-blue-400 opacity-80"
          style={{ left: `${leftPct}%`, width: `${width}%` }}
        />
      </div>
      <span className="w-28 text-xs text-gray-500 shrink-0">
        {min ? `€${fmt(min)}` : "–"} – {max ? `€${fmt(max)}` : "–"}
        {mid ? ` (Ø ${fmt(mid)})` : ""}
      </span>
    </div>
  );
}

// ── Skill pill ─────────────────────────────────────────────────────────────

function SkillPill({ skill, pct }: { skill: string; pct: number }) {
  const opacity = Math.max(0.3, pct / 100);
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-700"
      style={{ opacity }}
    >
      {skill}
      <span className="text-blue-400">{pct}%</span>
    </span>
  );
}

// ── Main ───────────────────────────────────────────────────────────────────

export default function MarketPage() {
  const router = useRouter();
  const [stats, setStats] = useState<MarketStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = auth.getAccess();
    // /market is an authenticated candidate feature, not a public marketing route.
    if (!token) { router.replace("/login?next=/market"); return; }

    marketApi
      .stats(token)
      .then(setStats)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) router.replace("/login");
        else setError("Statistiken konnten nicht geladen werden.");
      })
      .finally(() => setLoading(false));
  }, [router]);

  if (loading) {
    return (
      <>
        <Navbar />
        <div className="flex min-h-[60vh] items-center justify-center">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      </>
    );
  }

  if (error || !stats) {
    return (
      <>
        <Navbar />
        <div className="flex min-h-[60vh] items-center justify-center">
          <p className="text-red-500">{error ?? "Keine Daten."}</p>
        </div>
      </>
    );
  }

  const maxSkillCount = stats.top_skills[0]?.count ?? 1;
  const maxCatCount = stats.categories[0]?.count ?? 1;

  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-5xl px-4 py-8 space-y-8">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Markt-Insights</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Auswertung aus {stats.total_jobs.toLocaleString("de-DE")} Job-Inseraten
          </p>
        </div>

        {/* KPI row */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Card>
            <CardHeader className="pb-1">
              <CardTitle className="text-xs font-medium text-gray-500 uppercase tracking-wide">Jobs gesamt</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold text-gray-900">
                {stats.total_jobs.toLocaleString("de-DE")}
              </p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-1">
              <CardTitle className="text-xs font-medium text-gray-500 uppercase tracking-wide">Remote</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-3xl font-bold text-green-600">{stats.remote_pct}%</p>
              <p className="text-xs text-gray-400">{stats.remote_count} Stellen</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-1">
              <CardTitle className="text-xs font-medium text-gray-500 uppercase tracking-wide">Top Kategorie</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-lg font-bold text-gray-900 leading-tight">
                {stats.categories[0]?.category ?? "–"}
              </p>
              <p className="text-xs text-gray-400">{stats.categories[0]?.pct}% aller Jobs</p>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-1">
              <CardTitle className="text-xs font-medium text-gray-500 uppercase tracking-wide">Top Skill</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-lg font-bold text-blue-600 leading-tight">
                {stats.top_skills[0]?.skill ?? "–"}
              </p>
              <p className="text-xs text-gray-400">{stats.top_skills[0]?.pct}% der Jobs</p>
            </CardContent>
          </Card>
        </div>

        {/* Top skills */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Top 30 gefragte Skills</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {stats.top_skills.map((s) => (
              <HBar
                key={s.skill}
                label={s.skill}
                value={s.count}
                max={maxSkillCount}
                pct={s.pct}
                color="bg-blue-500"
              />
            ))}
          </CardContent>
        </Card>

        {/* Skill cloud (visual alternative) */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Skill-Cloud</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {stats.top_skills.map((s) => (
                <SkillPill key={s.skill} skill={s.skill} pct={s.pct} />
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Categories */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Jobs nach Kategorie</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {stats.categories.map((c) => (
              <HBar
                key={c.category}
                label={c.category}
                value={c.count}
                max={maxCatCount}
                pct={c.pct}
                color="bg-violet-500"
              />
            ))}
          </CardContent>
        </Card>

        {/* Salary benchmarks */}
        {stats.salary_by_category.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Gehalts-Benchmarks nach Kategorie</CardTitle>
              <p className="text-xs text-gray-400 mt-0.5">
                Ø Jahresgehalt (Brutto) – basiert auf Inseraten mit Gehaltsangabe
              </p>
            </CardHeader>
            <CardContent className="space-y-2">
              {stats.salary_by_category.map((s) => (
                <SalaryBar
                  key={s.category}
                  category={s.category}
                  min={s.salary_min_avg}
                  max={s.salary_max_avg}
                  mid={s.salary_mid}
                />
              ))}
            </CardContent>
          </Card>
        )}

        {/* Employment types */}
        {stats.employment_types.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Beschäftigungsarten</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-3">
              {stats.employment_types.map((e) => (
                <div
                  key={e.type}
                  className="rounded-lg border border-gray-200 bg-gray-50 px-4 py-2 text-center min-w-[100px]"
                >
                  <p className="text-xl font-bold text-gray-900">{e.count}</p>
                  <p className="text-xs text-gray-500 capitalize">{e.type}</p>
                </div>
              ))}
            </CardContent>
          </Card>
        )}

        {/* Personal skill gap vs market */}
        <SkillGapWidget />
      </main>
    </>
  );
}
