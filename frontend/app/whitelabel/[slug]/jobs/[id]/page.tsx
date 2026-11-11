"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { brandTextColor } from "@/lib/workspace-branding";
import { useBranding } from "@/lib/BrandingContext";
import { publicApi, type PublicJobRead } from "@/lib/api";

function Detail({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">{label}</dt>
      <dd className="text-sm text-gray-800">{value}</dd>
    </div>
  );
}

export default function PublicJobDetailPage() {
  const params = useParams();
  const jobId = params?.id as string;
  const branding = useBranding();
  const primary = branding.primary_color ?? "#2563eb";

  const [job, setJob] = useState<PublicJobRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!jobId) return;
    publicApi
      .getPublicJob(jobId, branding.slug)
      .then(setJob)
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false));
  }, [jobId, branding.slug]);

  if (loading) {
    return (
      <div className="flex justify-center py-24">
        <div
          className="animate-spin h-8 w-8 border-4 border-t-transparent rounded-full"
          style={{ borderColor: primary, borderTopColor: "transparent" }}
        />
      </div>
    );
  }

  if (notFound || !job) {
    return (
      <div className="max-w-2xl mx-auto px-6 py-20 text-center">
        <p className="text-xl font-bold text-gray-800 mb-2">Stelle nicht gefunden</p>
        <p className="text-gray-500 mb-6">Diese Stelle existiert nicht oder wurde entfernt.</p>
        <Link
          href={`/whitelabel/${branding.slug}/jobs`}
          className="text-sm hover:underline"
          style={{ color: "#1f2937" }}
        >
          ← Alle Stellen ansehen
        </Link>
      </div>
    );
  }

  const salaryText =
    job.salary_min && job.salary_max
      ? `${job.salary_min.toLocaleString("de-DE")} – ${job.salary_max.toLocaleString("de-DE")} € / Jahr`
      : job.salary_min
      ? `ab ${job.salary_min.toLocaleString("de-DE")} € / Jahr`
      : job.salary_max
      ? `bis ${job.salary_max.toLocaleString("de-DE")} € / Jahr`
      : null;

  return (
    <div className="max-w-3xl mx-auto px-6 py-12">
      {/* Breadcrumb */}
      <Link
        href={`/whitelabel/${branding.slug}/jobs`}
        className="text-sm mb-6 inline-flex items-center gap-1 hover:underline"
        style={{ color: "#1f2937" }}
      >
        ← Alle Stellen
      </Link>

      {/* Header card */}
      <div className="bg-white rounded-2xl border border-gray-200 p-8 mb-6">
        <div className="flex items-start justify-between gap-6 mb-6">
          <div className="min-w-0 break-words">
            <h1 className="text-2xl font-bold text-gray-900 mb-1">{job.title}</h1>
            <p className="text-gray-500 text-sm">
              {job.company}
              {job.location ? ` · ${job.location}` : ""}
            </p>
          </div>
          {/* Logo placeholder / tenant initial */}
          {branding.logo_url ? (
            <img referrerPolicy="no-referrer" src={branding.logo_url} alt={branding.name} className="h-12 max-w-20 shrink-0 rounded-lg object-contain" />
          ) : (
            <div
              className="h-12 w-12 rounded-xl flex items-center justify-center text-white font-bold text-lg flex-shrink-0"
              style={{ backgroundColor: primary, color: brandTextColor(primary) }}
            >
              {branding.name.charAt(0).toUpperCase()}
            </div>
          )}
        </div>

        {/* Meta details */}
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-5 mb-6">
          {job.employment_type && <Detail label="Anstellungsart" value={job.employment_type} />}
          <Detail label="Remote" value={job.is_remote ? "Ja" : "Nein"} />
          {salaryText && <Detail label="Gehalt" value={salaryText} />}
          {job.category && <Detail label="Kategorie" value={job.category} />}
        </dl>

        {/* Skills */}
        {job.required_skills.length > 0 && (
          <div className="mb-6">
            <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">Gesuchte Skills</p>
            <div className="flex flex-wrap gap-2">
              {job.required_skills.map((s) => (
                <span
                  key={s}
                  className="text-xs px-2.5 py-1 rounded-full border"
                  style={{ backgroundColor: `${primary}0f`, color: "#1f2937", borderColor: `${primary}33` }}
                >
                  {s}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Apply CTA */}
        <Link
          href={`/register?job=${job.id}&tenant=${branding.slug}`}
          className="inline-flex items-center gap-2 text-white font-semibold px-6 py-3 rounded-xl shadow hover:opacity-90 transition-opacity"
          style={{ backgroundColor: primary, color: brandTextColor(primary) }}
        >
          Jetzt bewerben
        </Link>
      </div>

      {/* Description */}
      {job.description && (
        <div className="bg-white rounded-2xl border border-gray-200 p-8">
          <h2 className="text-base font-semibold text-gray-900 mb-4">Stellenbeschreibung</h2>
          <div className="prose prose-sm max-w-none text-gray-700 whitespace-pre-wrap">
            {job.description}
          </div>
        </div>
      )}
    </div>
  );
}
