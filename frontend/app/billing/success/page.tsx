"use client";

import Link from "next/link";
import { useEffect } from "react";
import { clearModuleCache } from "@/lib/modules";

export default function BillingSuccessPage() {
  useEffect(() => {
    // Clear module cache so the new plan's modules load fresh
    clearModuleCache();
  }, []);

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="w-full max-w-md bg-white rounded-2xl shadow p-8 text-center">
        <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-green-100">
          <svg className="h-8 w-8 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        </div>
        <h1 className="text-2xl font-bold text-gray-900 mb-2">Zahlung erfolgreich!</h1>
        <p className="text-gray-500 text-sm mb-6">
          Dein Abonnement ist jetzt aktiv. Alle gebuchten Module stehen sofort zur Verfügung.
        </p>
        <Link
          href="/dashboard/plan"
          className="inline-block rounded-lg bg-blue-600 px-6 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 transition-colors"
        >
          Mein Plan ansehen
        </Link>
        <p className="mt-4">
          <Link href="/dashboard" className="text-sm text-gray-400 hover:text-gray-600">
            Zum Dashboard
          </Link>
        </p>
      </div>
    </div>
  );
}
