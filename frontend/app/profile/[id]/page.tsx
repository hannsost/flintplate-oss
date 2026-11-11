"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { profileApi, ApiError } from "@/lib/api";
import type { ProfileRead } from "@/lib/api";

function formatDate(d: string | null): string {
  if (!d) return "";
  const [year, month] = d.split("-");
  return `${month}/${year}`;
}

export default function PublicProfilePage() {
  const params = useParams();
  const profileId = params.id as string;
  const [profile, setProfile] = useState<ProfileRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!profileId) return;
    profileApi
      .getPublic(profileId)
      .then(setProfile)
      .catch((e) => {
        setError(e instanceof ApiError && e.status === 404
          ? "Profil nicht gefunden."
          : "Fehler beim Laden des Profils.");
      })
      .finally(() => setLoading(false));
  }, [profileId]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50 gap-4">
        <p className="text-gray-500">{error ?? "Profil nicht gefunden."}</p>
        <Link href="/" className="text-sm text-blue-600 hover:underline">← Zur Startseite</Link>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="border-b border-gray-200 bg-white px-4 py-3">
        <div className="mx-auto max-w-3xl flex items-center justify-between">
          <Link href="/" className="text-lg font-bold tracking-tight">
            palm<span className="text-blue-600">scout</span>
          </Link>
          <Link href="/login" className="text-sm text-gray-500 hover:text-gray-700">Einloggen →</Link>
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-4 py-8 space-y-6">
        {/* Profile header */}
        <div className="rounded-2xl bg-white border border-gray-200 shadow-sm p-6">
          {profile.headline && (
            <p className="text-lg font-semibold text-gray-900">{profile.headline}</p>
          )}
          <div className="mt-1 flex flex-wrap gap-3 text-sm text-gray-500">
            {profile.location && <span>📍 {profile.location}</span>}
            {profile.website && (
              <a href={profile.website} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
                🌐 Website
              </a>
            )}
            {profile.linkedin_url && (
              <a href={profile.linkedin_url} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">
                in LinkedIn
              </a>
            )}
          </div>
          {profile.summary && (
            <p className="mt-4 text-sm text-gray-700 leading-relaxed whitespace-pre-line">{profile.summary}</p>
          )}
        </div>

        {/* Skills */}
        {profile.skills.length > 0 && (
          <div className="rounded-2xl bg-white border border-gray-200 shadow-sm p-6">
            <h2 className="text-base font-semibold text-gray-900 mb-3">Skills</h2>
            <div className="flex flex-wrap gap-2">
              {profile.skills.map((s) => (
                <span
                  key={s.id}
                  className="rounded-full bg-blue-50 border border-blue-200 px-3 py-0.5 text-sm text-blue-700 font-medium capitalize"
                >
                  {s.name}
                  {s.level && <span className="text-blue-400 text-xs ml-1">· {s.level}</span>}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Work experience */}
        {profile.work_experiences.length > 0 && (
          <div className="rounded-2xl bg-white border border-gray-200 shadow-sm p-6">
            <h2 className="text-base font-semibold text-gray-900 mb-4">Berufserfahrung</h2>
            <div className="space-y-5">
              {profile.work_experiences.map((w) => (
                <div key={w.id} className="flex gap-4">
                  <div className="w-px bg-gray-200 mt-1.5 shrink-0 ml-2" />
                  <div className="pb-1 min-w-0">
                    <p className="font-medium text-gray-900">{w.title}</p>
                    <p className="text-sm text-gray-600">{w.company}{w.location ? ` · ${w.location}` : ""}</p>
                    <p className="text-xs text-gray-400 mt-0.5">
                      {formatDate(w.start_date)} – {w.is_current ? "Heute" : formatDate(w.end_date)}
                    </p>
                    {w.description && (
                      <p className="mt-1.5 text-xs text-gray-600 whitespace-pre-line leading-relaxed">{w.description}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Education */}
        {profile.educations.length > 0 && (
          <div className="rounded-2xl bg-white border border-gray-200 shadow-sm p-6">
            <h2 className="text-base font-semibold text-gray-900 mb-4">Ausbildung</h2>
            <div className="space-y-4">
              {profile.educations.map((e) => (
                <div key={e.id}>
                  <p className="font-medium text-gray-900">{e.institution}</p>
                  <p className="text-sm text-gray-600">
                    {[e.degree, e.field_of_study].filter(Boolean).join(" · ")}
                  </p>
                  <p className="text-xs text-gray-400 mt-0.5">
                    {formatDate(e.start_date)} – {formatDate(e.end_date)}
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Footer */}
        <p className="text-center text-xs text-gray-400 pb-4">
          Erstellt mit{" "}
          <Link href="/" className="text-blue-600 hover:underline font-medium">FlintPlate</Link>
        </p>
      </main>
    </div>
  );
}
