"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { brandTextColor } from "@/lib/workspace-branding";
import { publicApi, type TenantBranding } from "@/lib/api";
import { BrandingContext } from "@/lib/BrandingContext";

function BrandedHeader({ branding }: { branding: TenantBranding }) {
  const primary = branding.primary_color ?? "#2563eb";
  return (
    <header className="text-white shadow-sm" style={{ backgroundColor: primary, color: brandTextColor(primary) }}>
      <div className="max-w-6xl mx-auto px-4 py-4 flex flex-wrap gap-4 items-center justify-between">
        <Link href={`/whitelabel/${branding.slug}`} className="flex min-w-0 max-w-full items-center gap-3">
          {branding.logo_url ? (
            <img referrerPolicy="no-referrer" src={branding.logo_url} alt="" className="h-8 max-w-20 shrink-0 object-contain" />
          ) : (
            <div className="h-8 w-8 rounded-lg bg-white/20 flex items-center justify-center font-bold text-sm">
              {branding.name.charAt(0).toUpperCase()}
            </div>
          )}
          <span className="min-w-0 break-words text-lg font-semibold">{branding.name}</span>
        </Link>
        <nav className="flex items-center gap-4">
          <Link
            href={`/whitelabel/${branding.slug}/jobs`}
            className="text-sm hover:underline transition-colors"
          >
            Stellen
          </Link>
          <Link
            href="/login"
            className="text-sm hover:underline transition-colors"
          >
            Anmelden
          </Link>
          <Link
            href="/register"
            className="text-sm bg-white font-semibold px-4 py-2 rounded-lg hover:bg-gray-100 transition-colors"
            style={{ color: "#1f2937" }}
          >
            Registrieren
          </Link>
        </nav>
      </div>
    </header>
  );
}

function BrandedFooter({ branding }: { branding: TenantBranding }) {
  return (
    <footer className="border-t border-gray-200 bg-white py-6 mt-auto">
      <div className="max-w-6xl mx-auto px-6 flex flex-col sm:flex-row items-center justify-between gap-3 text-xs text-gray-600">
        <span>FlintPlate von neurofunken · {branding.name}</span>
        <span>
          <Link href="/privacy" className="hover:text-gray-600 mr-4">Datenschutz</Link>
          <Link href="/imprint" className="hover:text-gray-600">Impressum</Link>
        </span>
      </div>
    </footer>
  );
}

export default function WhiteLabelLayout({ children }: { children: React.ReactNode }) {
  const params = useParams();
  const slug = params?.slug as string;

  const [branding, setBranding] = useState<TenantBranding | null>(null);
  const [notFound, setNotFound] = useState(false);

  useEffect(() => {
    if (!slug) return;
    publicApi
      .getBrandingBySlug(slug)
      .then(setBranding)
      .catch(() => setNotFound(true));
  }, [slug]);

  if (notFound) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="text-center">
          <p className="text-2xl font-bold text-gray-800 mb-2">Karriereseite nicht gefunden</p>
          <p className="text-gray-500 mb-6">Diese Seite existiert nicht.</p>
          <Link href="/" className="text-blue-600 hover:underline text-sm">← Zur Startseite</Link>
        </div>
      </div>
    );
  }

  if (!branding) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50">
        <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full" />
      </div>
    );
  }

  return (
    <BrandingContext.Provider value={branding}>
      <div className="min-h-screen flex flex-col">
        <BrandedHeader branding={branding} />
        <main className="flex-1 bg-gray-50">
          {children}
        </main>
        <BrandedFooter branding={branding} />
      </div>
    </BrandingContext.Provider>
  );
}
