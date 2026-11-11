"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { recruiterApi, ApiError } from "@/lib/api";
import type { JobCreate } from "@/lib/api";
import { JobForm } from "@/components/recruiter/JobForm";

export default function NewJobPage() {
  const router = useRouter();

  async function handleCreate(data: JobCreate) {
    const token = auth.getAccess();
    if (!token) { router.push("/login"); return; }

    try {
      await recruiterApi.createJob(token, data);
      router.push("/dashboard/jobs");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        router.push("/login");
      }
      throw e;
    }
  }

  return (
    <>

      <main className="mx-auto max-w-2xl px-4 py-8">
        <div className="mb-6 flex items-center gap-3">
          <Link href="/dashboard/jobs" className="text-sm text-gray-500 hover:text-gray-700">
            ← Stellen
          </Link>
          <h1 className="text-xl font-bold text-gray-900">Neues Inserat erstellen</h1>
        </div>

        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <p className="mb-4 text-sm text-gray-600">Neue Stellen werden als Entwurf gespeichert. Inhalt und Veröffentlichungsdauer prüfst du anschließend in der Stellenübersicht.</p>
          <JobForm onSubmit={handleCreate} submitLabel="Entwurf speichern" />
        </div>
      </main>
    </>
  );
}
