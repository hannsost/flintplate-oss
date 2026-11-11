"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useBranding } from "@/lib/BrandingContext";
import { publicApi, type PublicJobRead } from "@/lib/api";

function SalaryLabel({ min, max }: { min: number | null; max: number | null }) {
  if (!min && !max) return null;
  const fmt = (v: number) =>
    v >= 1000 ? `${Math.round(v / 1000)}k` : `${v}`;
  const text = min && max ? `${fmt(min)} – ${fmt(max)} €` : min ? `ab ${fmt(min)} €` : `bis ${fmt(max!)} €`;
  return (
    <span className="text-xs bg-green-50 text-green-700 border border-green-200 px-2 py-0.5 rounded-full">
      {text}
    </span>
  );
}

export default function PublicJobsPage() {
  const branding = useBranding();
  const primary = branding.primary_color ?? "#2563eb";

  const [jobs, setJobs] = useState<PublicJobRead[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    publicApi
      .getPublicJobs(branding.slug)
      .then(setJobs)
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, [branding.slug]);

  return (
    <div className="max-w-4xl mx-auto px-6 py-12">
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">
          Offene Stellen bei {branding.name}
        </h1>
        <p className="text-sm text-gray-500">
          {loading ? "Stellen werden geladen …" : `${jobs.length} Stelle${jobs.length !== 1 ? "n" : ""} gefunden`}
        </p>
      </div>

      {loading && (
        <div className="flex justify-center py-20">
          <div className="animate-spin h-8 w-8 border-4 border-t-transparent rounded-full" style={{ borderColor: primary, borderTopColor: "transparent" }} />
        </div>
      )}

      {error && (
        <div className="text-center py-16 text-gray-400">
          <p className="text-lg font-medium mb-2">Stellen konnten nicht geladen werden.</p>
          <p className="text-sm">Bitte versuchen Sie es später erneut.</p>
        </div>
      )}

      {!loading && !error && jobs.length === 0 && (
        <div className="text-center py-16 text-gray-400">
          <p className="text-lg font-medium mb-2">Aktuell keine offenen Stellen</p>
          <p className="text-sm">Schauen Sie bald wieder vorbei.</p>
        </div>
      )}

      {!loading && !error && jobs.length > 0 && (
        <div className="flex flex-col gap-4">
          {jobs.map((job) => (
            <Link
              key={job.id}
              href={`/whitelabel/${branding.slug}/jobs/${job.id}`}
              className="group bg-white rounded-xl border border-gray-200 p-5 hover:border-gray-300 hover:shadow-sm transition-all"
            >
              <div className="flex items-start justify-between gap-4 mb-3">
                <div>
                  <h2 className="text-base font-semibold text-gray-900 group-hover:underline mb-0.5">
                    {job.title}
                  </h2>
                  <p className="text-sm text-gray-500">{job.company}{job.location ? ` · ${job.location}` : ""}</p>
                </div>
                <span
                  className="text-xs font-medium px-3 py-1 rounded-full whitespace-nowrap flex-shrink-0"
                  style={{ backgroundColor: `${primary}1a`, color: "#1f2937" }}
                >
                  Jetzt bewerben →
                </span>
              </div>
              {job.description && (
                <p className="text-sm text-gray-600 line-clamp-2 mb-3">
                  {job.description}
                </p>
              )}
              <div className="flex flex-wrap items-center gap-2">
                {job.is_remote && (
                  <span className="text-xs bg-blue-50 text-blue-700 border border-blue-200 px-2 py-0.5 rounded-full">Remote</span>
                )}
                {job.employment_type && (
                  <span className="text-xs bg-gray-100 text-gray-600 border border-gray-200 px-2 py-0.5 rounded-full">
                    {job.employment_type}
                  </span>
                )}
                <SalaryLabel min={job.salary_min} max={job.salary_max} />
                {job.required_skills.slice(0, 4).map((s) => (
                  <span key={s} className="text-xs bg-gray-50 text-gray-500 border border-gray-200 px-2 py-0.5 rounded-full">
                    {s}
                  </span>
                ))}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
