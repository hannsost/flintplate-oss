import { LEGAL } from "@/lib/legal-constants";
import Link from "next/link";
import { ChevronLeft } from "lucide-react";

interface LegalPageShellProps {
  title: string;
  lastUpdated: string;
  children: React.ReactNode;
  backHref?: string;
  backLabel?: string;
}

export function LegalPageShell({
  title,
  lastUpdated,
  children,
  backHref = "/",
  backLabel = "Zurück",
}: LegalPageShellProps) {
  return (
    <div className="min-h-screen bg-gray-50">
      <header className="sticky top-0 z-50 border-b border-gray-200 bg-white/90 backdrop-blur-sm">
        <div className="mx-auto flex h-14 max-w-4xl items-center justify-between px-4">
          <Link href="/" className="text-lg font-bold tracking-tight">
            palm<span className="text-blue-600">scout</span>
          </Link>
          <Link
            href={backHref}
            className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-800 transition-colors"
          >
            <ChevronLeft size={15} />
            {backLabel}
          </Link>
        </div>
      </header>

      <main className="mx-auto max-w-4xl px-4 py-12">
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900">{title}</h1>
          <p className="mt-1 text-sm text-gray-400">Stand: {lastUpdated}</p>
        </div>

        {!LEGAL.reviewed && <p role="note" className="mb-8 rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950">Entwurf für die Entwicklung: Betreiberangaben, Verträge und Datenschutzinformationen müssen vor dem öffentlichen Betrieb vervollständigt und rechtlich geprüft werden.</p>}
        <div className="legal-content">
          {children}
        </div>
      </main>

      <footer className="border-t border-gray-200 py-6 text-center text-xs text-gray-400">
        <div className="flex items-center justify-center gap-4 flex-wrap">
          <Link href="/legal/impressum" className="hover:text-gray-600">Impressum</Link>
          <Link href="/legal/datenschutz" className="hover:text-gray-600">Datenschutz</Link>
          <Link href="/legal/agb-b2b" className="hover:text-gray-600">AGB (B2B)</Link>
          <Link href="/legal/nutzungsbedingungen" className="hover:text-gray-600">Nutzungsbedingungen</Link>
        </div>
      </footer>
    </div>
  );
}
