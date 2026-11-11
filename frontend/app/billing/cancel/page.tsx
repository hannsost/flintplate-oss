"use client";

import Link from "next/link";

export default function BillingCancelPage() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="w-full max-w-md bg-white rounded-2xl shadow p-8 text-center">
        <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-gray-100">
          <svg className="h-8 w-8 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </div>
        <h1 className="text-2xl font-bold text-gray-900 mb-2">Abonnement-Abschluss abgebrochen</h1>
        <p className="text-gray-500 text-sm mb-6">
          Du kannst jederzeit ein Upgrade durchführen. Deine aktuellen Module bleiben aktiv.
        </p>
        <Link
          href="/dashboard/plan"
          className="inline-block rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 transition-colors"
        >
          Zurück zu Mein Plan
        </Link>
      </div>
    </div>
  );
}
