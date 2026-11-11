"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { auth } from "@/lib/auth";
import {
  authApi,
  applicationsApi,
  jobsApi,
  savedJobsApi,
  notificationsApi,
  profileApi,
  ApiError,
} from "@/lib/api";
import type { UserRead, KanbanBoard, JobMatchResult, NotificationRead, ProfileRead } from "@/lib/api";
import { Navbar } from "@/components/layout/Navbar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

function StatCard({ label, value, href, accent }: {
  label: string;
  value: number | string;
  href: string;
  accent?: string;
}) {
  return (
    <Link href={href}>
      <Card className="hover:shadow-md transition-shadow cursor-pointer">
        <CardHeader className="pb-1">
          <CardTitle className="text-xs font-medium text-gray-500 uppercase tracking-wide">{label}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className={`text-3xl font-bold ${accent ?? "text-gray-900"}`}>{value}</p>
        </CardContent>
      </Card>
    </Link>
  );
}

export default function CandidateHomePage() {
  const router = useRouter();
  const [user, setUser] = useState<UserRead | null>(null);
  const [profile, setProfile] = useState<ProfileRead | null>(null);
  const [board, setBoard] = useState<KanbanBoard | null>(null);
  const [savedCount, setSavedCount] = useState(0);
  const [topJobs, setTopJobs] = useState<JobMatchResult[]>([]);
  const [notifications, setNotifications] = useState<NotificationRead[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = auth.getAccess();
    // /home is an authenticated candidate dashboard; /landing is the public marketing page.
    if (!token) { router.replace("/login?next=/home"); return; }

    Promise.allSettled([
      authApi.me(token),
      applicationsApi.getKanban(token),
      savedJobsApi.listIds(token),
      jobsApi.recommended(token, { page: 1, page_size: 5 }),
      notificationsApi.list(token),
      profileApi.getMe(token),
    ]).then(([userRes, boardRes, savedRes, jobsRes, notifRes, profileRes]) => {
      if (userRes.status === "fulfilled") {
        const u = userRes.value;
        setUser(u);
        if (u.role === "recruiter") { router.replace("/dashboard"); return; }
      } else {
        router.replace("/login");
        return;
      }
      if (boardRes.status === "fulfilled") setBoard(boardRes.value);
      if (savedRes.status === "fulfilled") setSavedCount(savedRes.value.length);
      if (jobsRes.status === "fulfilled") setTopJobs(jobsRes.value.jobs);
      if (notifRes.status === "fulfilled") setNotifications(notifRes.value.notifications.slice(0, 5));
      if (profileRes.status === "fulfilled") setProfile(profileRes.value);
    }).finally(() => setLoading(false));
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

  // Application stats from Kanban
  const statusCounts: Record<string, number> = {};
  board?.columns.forEach((col) => {
    statusCounts[col.status as string] = col.applications.length;
  });
  const totalApps = board?.total ?? 0;
  const interviewCount = statusCounts["interview"] ?? 0;
  const offerCount = statusCounts["offer"] ?? 0;

  const MODULE_LINKS = [
    { href: "/jobs", icon: "🔍", label: "Jobs", desc: "Empfohlene Stellen entdecken" },
    { href: "/applications", icon: "📋", label: "Bewerbungen", desc: "Kanban-Board & Tracker" },
    { href: "/cover-letters", icon: "✉️", label: "Anschreiben", desc: "KI-generierte Anschreiben" },
    { href: "/interview-prep", icon: "🎤", label: "Interview", desc: "Fragen & Antworten üben" },
    { href: "/market", icon: "📊", label: "Markt", desc: "Skills & Gehalt im Vergleich" },
    { href: "/profile", icon: "👤", label: "Profil", desc: "CV, Skills & Erfahrungen" },
  ];

  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-5xl px-4 py-8 space-y-8">

        {/* Greeting */}
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            Guten Tag{user?.full_name ? `, ${user.full_name.split(" ")[0]}` : ""}!
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">Deine Jobsuche auf einen Blick.</p>
        </div>

        {/* Profile completeness banner */}
        {profile && profile.completeness_score < 80 && (
          <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 flex items-center gap-4">
            <div className="flex-1 min-w-0">
              <p className="text-sm font-semibold text-amber-800">Profil vervollständigen</p>
              <p className="text-xs text-amber-600 mt-0.5">
                Dein Profil ist zu {profile.completeness_score}% vollständig – ein vollständiges Profil erhöht deine Match-Chancen deutlich.
              </p>
              <div className="mt-2 h-1.5 w-full rounded-full bg-amber-200">
                <div
                  className="h-1.5 rounded-full bg-amber-500 transition-all"
                  style={{ width: `${profile.completeness_score}%` }}
                />
              </div>
            </div>
            <Link href="/profile" className="shrink-0 rounded-lg bg-amber-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-amber-700 transition-colors">
              Profil bearbeiten
            </Link>
          </div>
        )}

        {/* KPI row */}
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <StatCard label="Bewerbungen" value={totalApps} href="/applications" accent="text-blue-600" />
          <StatCard label="Interviews" value={interviewCount} href="/applications" accent="text-purple-600" />
          <StatCard label="Angebote" value={offerCount} href="/applications" accent="text-green-600" />
          <StatCard label="Gemerkte Jobs" value={savedCount} href="/jobs/saved" accent="text-amber-600" />
        </div>

        {/* Top job recommendations */}
        {topJobs.length > 0 && (
          <div>
            <div className="flex items-center justify-between mb-3">
              <p className="text-xs font-medium text-gray-400 uppercase tracking-wide">Top-Empfehlungen</p>
              <Link href="/jobs" className="text-xs text-blue-600 hover:underline">Alle Jobs →</Link>
            </div>
            <div className="space-y-2">
              {topJobs.map(({ job, score }) => (
                <Link key={job.id} href="/jobs">
                  <div className="rounded-xl border border-gray-200 bg-white p-3 hover:shadow-md transition-shadow flex items-center justify-between gap-4 cursor-pointer">
                    <div className="min-w-0 flex-1">
                      <p className="font-medium text-gray-900 truncate text-sm">{job.title}</p>
                      <p className="text-xs text-gray-500">
                        {job.company}{job.location ? ` · ${job.location}` : ""}
                        {job.is_remote && " · Remote"}
                      </p>
                    </div>
                    <span className={`shrink-0 text-xs font-semibold px-2 py-0.5 rounded-full ${
                      score >= 75 ? "bg-green-100 text-green-700" :
                      score >= 50 ? "bg-yellow-100 text-yellow-700" :
                      "bg-gray-100 text-gray-600"
                    }`}>
                      {Math.round(score)}% Match
                    </span>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )}

        {/* Module navigation */}
        <div>
          <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-3">Module</p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {MODULE_LINKS.map((m) => (
              <Link key={m.href} href={m.href}>
                <div className="rounded-xl border border-gray-200 bg-white p-4 hover:shadow-md hover:border-blue-200 transition-all cursor-pointer h-full">
                  <p className="text-2xl mb-2">{m.icon}</p>
                  <p className="font-semibold text-sm text-gray-900">{m.label}</p>
                  <p className="text-[11px] text-gray-400 mt-0.5 leading-tight">{m.desc}</p>
                </div>
              </Link>
            ))}
          </div>
        </div>

        {/* Recent notifications */}
        {notifications.length > 0 && (
          <div>
            <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-3">Letzte Benachrichtigungen</p>
            <Card>
              <CardContent className="divide-y divide-gray-50 p-0">
                {notifications.map((n) => (
                  <div key={n.id} className={`px-4 py-3 ${!n.read_at ? "bg-blue-50/40" : ""}`}>
                    <p className="text-sm font-medium text-gray-900 leading-snug">{n.title}</p>
                    <p className="text-xs text-gray-500 mt-0.5">{n.body}</p>
                    <p className="text-[11px] text-gray-400 mt-1">
                      {new Date(n.created_at).toLocaleDateString("de-DE", {
                        day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
                      })}
                    </p>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>
        )}

        {/* Application status breakdown */}
        {totalApps > 0 && (
          <div>
            <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-3">Bewerbungs-Status</p>
            <div className="flex flex-wrap gap-2">
              {Object.entries(statusCounts)
                .filter(([, count]) => count > 0)
                .sort((a, b) => b[1] - a[1])
                .map(([status, count]) => {
                  const labels: Record<string, string> = {
                    research: "Recherche", applied: "Beworben", screening: "Screening",
                    interview: "Interview", offer: "Angebot", rejected: "Abgelehnt",
                    withdrawn: "Zurückgezogen",
                  };
                  const colors: Record<string, string> = {
                    applied: "bg-blue-100 text-blue-700", screening: "bg-yellow-100 text-yellow-700",
                    interview: "bg-purple-100 text-purple-700", offer: "bg-blue-100 text-blue-700",
                    rejected: "bg-red-100 text-red-600", withdrawn: "bg-gray-100 text-gray-500",
                    research: "bg-gray-100 text-gray-500",
                  };
                  return (
                    <span key={status} className={`rounded-full px-3 py-1 text-xs font-medium ${colors[status] ?? "bg-gray-100 text-gray-500"}`}>
                      {labels[status] ?? status}: <strong>{count}</strong>
                    </span>
                  );
                })}
            </div>
          </div>
        )}

        {/* Empty state */}
        {totalApps === 0 && topJobs.length === 0 && (
          <Card>
            <CardContent className="py-12 text-center">
              <p className="text-4xl mb-4">🚀</p>
              <p className="text-lg font-semibold text-gray-900 mb-2">Bereit für deinen nächsten Job?</p>
              <p className="text-sm text-gray-500 mb-6">
                Vervollständige dein Profil und entdecke passende Stellen.
              </p>
              <div className="flex justify-center gap-3">
                <Link href="/profile"><Button variant="outline">Profil bearbeiten</Button></Link>
                <Link href="/jobs"><Button>Jobs entdecken</Button></Link>
              </div>
            </CardContent>
          </Card>
        )}
      </main>
    </>
  );
}
