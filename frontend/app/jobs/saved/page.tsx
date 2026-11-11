"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { savedJobsApi, ApiError } from "@/lib/api";
import type { JobPosting } from "@/lib/api";
import { Navbar } from "@/components/layout/Navbar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { normalizeSkills } from "@/lib/skills";

function formatSalary(min: number | null, max: number | null): string {
  if (!min && !max) return "";
  const fmt = (n: number) => `${Math.round(n / 1000)}k`;
  if (min && max) return `€${fmt(min)}–${fmt(max)}`;
  if (min) return `ab €${fmt(min)}`;
  return `bis €${fmt(max!)}`;
}

export default function SavedJobsPage() {
  const router = useRouter();
  const [jobs, setJobs] = useState<JobPosting[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [removingId, setRemovingId] = useState<string | null>(null);

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) { router.replace("/login"); return; }

    savedJobsApi
      .list(token)
      .then(setJobs)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) router.replace("/login");
        else setError("Gemerkte Jobs konnten nicht geladen werden.");
      })
      .finally(() => setLoading(false));
  }, [router]);

  async function handleRemove(jobId: string) {
    const token = auth.getAccess();
    if (!token) return;
    setRemovingId(jobId);
    try {
      await savedJobsApi.unsave(token, jobId);
      setJobs((prev) => prev.filter((j) => j.id !== jobId));
    } catch {
      // silently ignore
    } finally {
      setRemovingId(null);
    }
  }

  return (
    <>
      <Navbar />
      <main className="mx-auto max-w-3xl px-4 py-8">
        <div className="flex items-center justify-between mb-6">
          <div>
            <div className="flex items-center gap-3 mb-1">
              <Link href="/jobs" className="text-sm text-gray-500 hover:text-gray-700">← Jobs</Link>
            </div>
            <h1 className="text-xl font-bold text-gray-900">Gemerkte Jobs</h1>
            {!loading && (
              <p className="text-sm text-gray-400 mt-0.5">{jobs.length} Job{jobs.length !== 1 ? "s" : ""} gespeichert</p>
            )}
          </div>
        </div>

        {error && <p className="text-sm text-red-600 mb-4">{error}</p>}

        {loading ? (
          <div className="flex justify-center py-16">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
          </div>
        ) : jobs.length === 0 ? (
          <div className="text-center py-16 text-gray-400">
            <p className="text-4xl mb-4">☆</p>
            <p className="text-lg mb-2">Noch keine Jobs gemerkt</p>
            <p className="text-sm mb-6">Klicke auf &quot;Merken&quot; in der Jobs-Liste, um Jobs hier zu speichern.</p>
            <Link href="/jobs">
              <Button>Jobs entdecken</Button>
            </Link>
          </div>
        ) : (
          <div className="space-y-3">
            {jobs.map((job) => (
              <Card key={job.id} className="hover:shadow-md transition-shadow">
                <CardContent className="p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap mb-1">
                        <h3 className="font-semibold text-gray-900 truncate">{job.title}</h3>
                        {job.is_remote && (
                          <Badge variant="secondary" className="text-xs shrink-0">Remote</Badge>
                        )}
                        {job.category && (
                          <Badge variant="secondary" className="text-xs shrink-0">{job.category}</Badge>
                        )}
                      </div>
                      <p className="text-sm text-gray-500">
                        {job.company}
                        {job.location && <span> · {job.location}</span>}
                        {formatSalary(job.salary_min, job.salary_max) && (
                          <span className="text-blue-600 font-medium"> · {formatSalary(job.salary_min, job.salary_max)}</span>
                        )}
                      </p>
                      {job.required_skills.length > 0 && (
                        <div className="mt-2 flex flex-wrap gap-1">
                          {normalizeSkills(job.required_skills).slice(0, 6).map((s) => (
                            <span key={s} className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600">{s}</span>
                          ))}
                          {job.required_skills.length > 6 && (
                            <span className="text-xs text-gray-400">+{job.required_skills.length - 6}</span>
                          )}
                        </div>
                      )}
                    </div>
                    <div className="shrink-0 flex flex-col gap-2 items-end">
                      {job.url && (
                        <a
                          href={job.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs text-blue-600 hover:underline"
                        >
                          Zur Stelle →
                        </a>
                      )}
                      <button
                        onClick={() => handleRemove(job.id)}
                        disabled={removingId === job.id}
                        className="text-xs text-gray-400 hover:text-red-500 transition-colors"
                      >
                        {removingId === job.id ? "…" : "✕ Entfernen"}
                      </button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </main>
    </>
  );
}
