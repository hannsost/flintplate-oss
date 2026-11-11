"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";
import { candidateApi, type CandidateInterviewRead } from "@/lib/api";
import { Video } from "lucide-react";

const STATUS_COLORS: Record<string, string> = {
  proposed: "bg-yellow-100 text-yellow-700 border-yellow-200",
  confirmed: "bg-green-100 text-green-700 border-green-200",
  declined: "bg-red-100 text-red-600 border-red-200",
  cancelled: "bg-gray-100 text-gray-500 border-gray-200",
};

const STATUS_LABELS: Record<string, string> = {
  proposed: "Vorgeschlagen",
  confirmed: "Bestätigt",
  declined: "Abgelehnt",
  cancelled: "Abgesagt",
};

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("de-DE", {
    weekday: "short",
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function WorkerInterviewsPage() {
  const router = useRouter();
  const [interviews, setInterviews] = useState<CandidateInterviewRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    const token = auth.getAccess();
    if (!token) { router.push("/login"); return; }
    candidateApi
      .listInterviews(token)
      .then(setInterviews)
      .catch(() => setError("Fehler beim Laden der Interviews."))
      .finally(() => setLoading(false));
  }, [router]);

  useEffect(() => { load(); }, [load]);

  async function handleRespond(iv: CandidateInterviewRead, newStatus: "confirmed" | "declined") {
    const token = auth.getAccess();
    if (!token) return;
    try {
      await candidateApi.respondInterview(token, iv.application_id, newStatus);
      setInterviews((prev) =>
        prev.map((x) => (x.id === iv.id ? { ...x, status: newStatus } : x)),
      );
    } catch {
      alert("Aktion fehlgeschlagen.");
    }
  }

  const now = new Date();

  return (
    <div className="min-h-screen bg-gray-50">
      <main className="mx-auto max-w-3xl px-4 py-8 space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Meine Interviews</h1>
          <p className="mt-1 text-sm text-gray-500">Ihre geplanten Vorstellungsgespräche</p>
        </div>

        <div className="rounded-2xl border border-gray-200 bg-white shadow-sm overflow-hidden">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
            </div>
          ) : error ? (
            <div className="py-16 text-center text-sm text-red-500">{error}</div>
          ) : interviews.length === 0 ? (
            <div className="py-16 text-center text-sm text-gray-400">
              Keine Interviews geplant.
            </div>
          ) : (
            <div className="divide-y divide-gray-100">
              {interviews.map((iv) => {
                const isPast = new Date(iv.scheduled_at) < now;
                const isUpcoming = !isPast && iv.status === "confirmed";
                return (
                  <div
                    key={iv.id}
                    className={`px-5 py-4 flex items-center justify-between gap-4 ${isPast ? "opacity-60" : ""}`}
                  >
                    <div className="min-w-0 space-y-1">
                      <p className="font-medium text-gray-900 truncate">{iv.job_title}</p>
                      <p className="text-xs text-gray-500">
                        {formatDateTime(iv.scheduled_at)}
                        {isPast && <span className="ml-1 text-gray-400">(vergangen)</span>}
                      </p>
                    </div>

                    <div className="flex items-center gap-2 flex-shrink-0 flex-wrap justify-end">
                      <span
                        className={`rounded-full border px-2.5 py-0.5 text-xs font-medium ${
                          STATUS_COLORS[iv.status] ?? "bg-gray-100 text-gray-500"
                        }`}
                      >
                        {STATUS_LABELS[iv.status] ?? iv.status}
                      </span>

                      {iv.status === "proposed" && (
                        <>
                          <button
                            onClick={() => handleRespond(iv, "confirmed")}
                            className="rounded border border-green-200 bg-green-50 px-2 py-0.5 text-xs text-green-700 hover:bg-green-100"
                          >
                            Annehmen
                          </button>
                          <button
                            onClick={() => handleRespond(iv, "declined")}
                            className="rounded border border-red-200 bg-red-50 px-2 py-0.5 text-xs text-red-600 hover:bg-red-100"
                          >
                            Ablehnen
                          </button>
                        </>
                      )}

                      {isUpcoming && (
                        <button
                          onClick={() => router.push(`/worker/interviews/room/${iv.id}`)}
                          className="flex items-center gap-1 rounded border border-blue-200 bg-blue-50 px-2 py-0.5 text-xs text-blue-700 hover:bg-blue-100 font-medium"
                        >
                          <Video size={11} />
                          Beitreten
                        </button>
                      )}

                      {iv.meeting_url && (
                        <a
                          href={iv.meeting_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="rounded border border-gray-200 px-2 py-0.5 text-xs text-gray-600 hover:border-gray-400"
                        >
                          Meeting
                        </a>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
