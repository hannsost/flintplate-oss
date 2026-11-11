"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { recruiterApi, ApiError } from "@/lib/api";
import type { JobPosting, JobCreate } from "@/lib/api";
import { JobForm } from "@/components/recruiter/JobForm";

export default function EditJobPage() {
  const router = useRouter();
  const params = useParams();
  const jobId = params.id as string;

  const [job, setJob] = useState<JobPosting | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) { router.push("/login"); return; }

    recruiterApi
      .getJob(token, jobId)
      .then(setJob)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) router.push("/login");
        else setError("Fehler beim Laden.");
      })
      .finally(() => setLoading(false));
  }, [jobId, router]);

  async function handleUpdate(data: JobCreate) {
    const token = auth.getAccess();
    if (!token) { router.push("/login"); return; }

    try {
      if (!job) return;
      await recruiterApi.updateJob(token, jobId, { ...data, expected_version: job.version });
      router.push("/dashboard/jobs");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) router.push("/login");
      throw e;
    }
  }

  if (loading) {
    return (
      <>

        <div className="flex min-h-[60vh] items-center justify-center">
          <p className="text-gray-500">Lade Inserat…</p>
        </div>
      </>
    );
  }

  if (error || !job) {
    return (
      <>

        <div className="flex min-h-[60vh] items-center justify-center">
          <p className="text-red-500">{error ?? "Job nicht gefunden."}</p>
        </div>
      </>
    );
  }

  return (
    <>

      <main className="mx-auto max-w-2xl px-4 py-8">
        <div className="mb-6 flex items-center gap-3">
          <Link href="/dashboard/jobs" className="text-sm text-gray-500 hover:text-gray-700">
            ← Stellen
          </Link>
          <h1 className="text-xl font-bold text-gray-900">Inserat bearbeiten</h1>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <p className="mb-4 text-sm text-gray-600">Gespeicherte Änderungen setzen die Stelle auf Entwurf. Prüfe und veröffentliche sie anschließend erneut.</p>
          <JobForm initial={job} onSubmit={handleUpdate} submitLabel="Änderungen speichern" />
        </div>
      </main>
    </>
  );
}
