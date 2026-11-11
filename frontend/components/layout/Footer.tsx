import Link from "next/link";

export function Footer() {
  return (
    <footer className="border-t border-gray-200 bg-white px-0 pt-6 pb-24 sm:pb-6">
      <div className="mx-auto max-w-6xl px-4">
        <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-between">
          <span className="text-sm font-semibold tracking-tight">
            palm<span className="text-blue-600">scout</span>
            <span className="ml-2 text-xs font-normal text-gray-600">
              © {new Date().getFullYear()} neurofunken
            </span>
          </span>

          <nav className="flex flex-wrap items-center justify-center gap-x-5 gap-y-1 text-xs text-gray-500">
            <Link href="/legal/impressum" className="hover:text-gray-800 transition-colors">
              Impressum
            </Link>
            <Link href="/legal/datenschutz" className="hover:text-gray-800 transition-colors">
              Datenschutz
            </Link>
            <Link href="/legal/agb-b2b" className="hover:text-gray-800 transition-colors">
              AGB (Unternehmen)
            </Link>
            <Link href="/legal/nutzungsbedingungen" className="hover:text-gray-800 transition-colors">
              Nutzungsbedingungen
            </Link>
          </nav>
        </div>
      </div>
    </footer>
  );
}
