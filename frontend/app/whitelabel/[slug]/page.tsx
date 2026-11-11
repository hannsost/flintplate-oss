"use client";

import Link from "next/link";
import { brandTextColor } from "@/lib/workspace-branding";
import { useBranding } from "@/lib/BrandingContext";

export default function WhiteLabelLandingPage() {
  const branding = useBranding();
  const primary = branding.primary_color ?? "#2563eb";

  return (
    <>
      {/* Hero */}
      <section className="max-w-4xl mx-auto px-6 py-20 text-center">
        <div
          className="inline-block text-xs font-semibold px-3 py-1 rounded-full mb-6"
          style={{ backgroundColor: `${primary}1a`, color: "#1f2937" }}
        >
          Recruiting-Plattform
        </div>
        <h1 className="text-4xl md:text-5xl font-bold text-gray-900 mb-6">
          Recruiting neu gedacht –<br />
          <span style={{ color: "#1f2937" }}>powered by {branding.name}</span>
        </h1>
        <p className="text-lg text-gray-500 mb-10 max-w-2xl mx-auto">
          Bewerben Sie sich direkt bei {branding.name}. Schnell, unkompliziert und mit
          KI-gestützter Matching-Technologie.
        </p>
        <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
          <Link
            href={`/whitelabel/${branding.slug}/jobs`}
            className="text-white font-semibold px-8 py-3 rounded-xl text-base shadow hover:opacity-90 transition-opacity"
            style={{ backgroundColor: primary, color: brandTextColor(primary) }}
          >
            Offene Stellen ansehen
          </Link>
          <Link
            href="/login"
            className="border border-gray-300 text-gray-700 font-semibold px-8 py-3 rounded-xl text-base hover:bg-gray-100 transition-colors"
          >
            Bereits registriert?
          </Link>
        </div>
      </section>

      {/* Feature strip */}
      <section className="max-w-4xl mx-auto px-6 pb-16 grid grid-cols-1 sm:grid-cols-3 gap-6">
        {[
          { title: "KI-Matching", body: "Ihr Profil wird automatisch mit passenden Stellen abgeglichen." },
          { title: "Schnelle Bewerbung", body: "CV hochladen, Profil ausfüllen – fertig in unter 5 Minuten." },
          { title: "Echtzeit-Status", body: "Verfolgen Sie den Status Ihrer Bewerbung jederzeit live." },
        ].map((f) => (
          <div key={f.title} className="bg-white rounded-xl border border-gray-200 p-5">
            <h3 className="font-semibold text-gray-900 mb-2">{f.title}</h3>
            <p className="text-sm text-gray-500">{f.body}</p>
          </div>
        ))}
      </section>
    </>
  );
}
