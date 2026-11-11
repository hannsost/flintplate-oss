"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { recruiterApi, type JobPosting } from "@/lib/api";
import { auth } from "@/lib/auth";
import { JobPublicationControls } from "@/components/recruiter/JobPublicationControls";
import { Button } from "@/components/ui/button";

export default function ImportedJobPublications() {
  const [jobs, setJobs] = useState<JobPosting[]>([]);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    const token = auth.getAccess(); if (!token) return;
    setLoading(true); setError("");
    try { setJobs(await recruiterApi.importedJobs(token, offset)); }
    catch (e) { setError(e instanceof Error ? e.message : "Importe konnten nicht geladen werden."); }
    finally { setLoading(false); }
  }, [offset]);
  useEffect(() => { void load(); }, [load]);
  return <main className="mx-auto max-w-4xl space-y-5 px-4 py-8">
    <Link href="/admin/import-runs" className="text-sm text-blue-700 underline">← Job-Import</Link>
    <h1 className="text-2xl font-bold">Importierte Stellen prüfen</h1>
    <p className="text-sm text-gray-700">Importe bleiben zunächst Entwürfe. Prüfe Quellen, Inhalte und Veröffentlichungsrechte für jede Stelle. Eine Freigabe bestätigt keine unabhängige Arbeitgeberprüfung.</p>
    {error && <p role="alert" className="text-red-700">{error}</p>}
    {loading ? <p role="status">Laden…</p> : jobs.map(job => <article key={job.id} className="rounded-xl border border-gray-200 bg-white p-5">
      <h2 className="text-lg font-semibold break-words">{job.title}</h2>
      <p className="text-sm text-gray-600">{job.company} · {job.location || "Kein Arbeitsort"} · Quelle: {job.source}</p>
      <JobPublicationControls job={job} imported onChange={updated => setJobs(previous => previous.map(item => item.id === updated.id ? updated : item))} />
    </article>)}
    {!loading && !jobs.length && <p>Keine weiteren Importe vorhanden.</p>}
    <div className="flex gap-3">
      <Button variant="outline" disabled={loading || offset === 0} onClick={() => setOffset(value => Math.max(0, value - 50))}>Zurück</Button>
      <Button variant="outline" disabled={loading || jobs.length < 50} onClick={() => setOffset(value => value + 50)}>Weiter</Button>
      <Button variant="ghost" onClick={load}>Neu laden</Button>
    </div>
  </main>;
}
