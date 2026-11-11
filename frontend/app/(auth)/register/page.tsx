"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { authApi, ApiError } from "@/lib/api";
import { auth } from "@/lib/auth";
import { Footer } from "@/components/layout/Footer";

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({ full_name: "", email: "", password: "" });
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [aiOptIn, setAiOptIn] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!termsAccepted) {
      setError("Bitte akzeptiere die Nutzungsbedingungen und Datenschutzrichtlinie.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const tokens = await authApi.register(form);
      auth.setTokens(tokens.access_token, tokens.refresh_token);
      // Update consent (non-blocking)
      authApi.updateConsent(tokens.access_token, {
        terms_accepted: true,
        ai_opt_in: aiOptIn,
      }).catch(() => {});
      router.push("/profile");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Registrierung fehlgeschlagen. Bitte versuche es erneut.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-gray-50">
    <div className="flex flex-1 items-center justify-center">
      <div className="w-full max-w-md bg-white rounded-2xl shadow p-8">
        <h1 className="text-2xl font-bold mb-6 text-gray-900">Konto erstellen</h1>

        {error && (
          <div className="mb-4 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
            <input
              type="text"
              required
              value={form.full_name}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Max Mustermann"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">E-Mail</label>
            <input
              type="email"
              required
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="name@beispiel.de"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Passwort</label>
            <input
              type="password"
              required
              minLength={8}
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Mind. 8 Zeichen"
            />
          </div>

          {/* GDPR consent */}
          <div className="rounded-lg bg-gray-50 border border-gray-200 p-4 space-y-3">
            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox"
                required
                checked={termsAccepted}
                onChange={(e) => setTermsAccepted(e.target.checked)}
                className="mt-0.5 rounded border-gray-300"
              />
              <span className="text-xs text-gray-600 leading-relaxed">
                Ich akzeptiere die{" "}
                <Link href="/legal/nutzungsbedingungen" target="_blank" className="text-blue-600 hover:underline">Nutzungsbedingungen</Link>
                {" "}und{" "}
                <Link href="/legal/datenschutz" target="_blank" className="text-blue-600 hover:underline">Datenschutzrichtlinie</Link>
                . Meine Daten werden DSGVO-konform verarbeitet. *
              </span>
            </label>
            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={aiOptIn}
                onChange={(e) => setAiOptIn(e.target.checked)}
                className="mt-0.5 rounded border-gray-300"
              />
              <span className="text-xs text-gray-600 leading-relaxed">
                Ich stimme der KI-gestützten Analyse meines Profils zu (CV-Parser, Job-Matching,
                Anschreiben-Generator). Diese Einwilligung ist freiwillig und jederzeit widerrufbar.
              </span>
            </label>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {loading ? "Wird erstellt…" : "Registrieren"}
          </button>
        </form>

        <p className="mt-5 text-center text-sm text-gray-500">
          Bereits registriert?{" "}
          <Link href="/login" className="text-blue-600 hover:underline font-medium">
            Anmelden
          </Link>
        </p>
        <p className="mt-2 text-center text-sm text-gray-500">
          Personalvermittler oder Unternehmen?{" "}
          <Link href="/register/recruiter" className="text-blue-600 hover:underline font-medium">
            Recruiter-Zugang erstellen
          </Link>
        </p>
      </div>
    </div>
    <Footer />
    </div>
  );
}
