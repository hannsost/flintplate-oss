"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { authApi, ApiError } from "@/lib/api";
import { auth } from "@/lib/auth";
import { Footer } from "@/components/layout/Footer";

export default function LoginPage() {
  const router = useRouter();
  const [form, setForm] = useState({ email: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const tokens = await authApi.login(form.email, form.password);
      auth.setTokens(tokens.access_token, tokens.refresh_token);
      const user = auth.getUser();
      const next = new URLSearchParams(window.location.search).get("next");
      // Only honor the two explicitly auth-gated legacy feature routes.
      const requestedRoute = next === "/home" || next === "/market" ? next : null;
      if (requestedRoute && user?.role === "candidate") {
        router.push(requestedRoute);
      } else if (user?.role === "worker") {
        router.push("/worker");
      } else if (user?.role === "admin" && !user.tenant_id) {
        router.push("/admin");
      } else if (user?.role === "recruiter" || user?.role === "admin") {
        router.push("/dashboard");
      } else if (user?.role === "support") {
        router.push("/support");
      } else {
        router.push("/profile");
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError("E-Mail oder Passwort falsch.");
      } else if (err instanceof ApiError) {
        setError(err.detail || "Anmeldung fehlgeschlagen. Bitte versuche es erneut.");
      } else {
        setError("Server nicht erreichbar. Bitte versuche es erneut.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-gray-50">
    <div className="flex flex-1 items-center justify-center">
      <div className="w-full max-w-md bg-white rounded-2xl shadow p-8">
        <h1 className="text-2xl font-bold mb-6 text-gray-900">Anmelden</h1>

        {error && (
          <div role="alert" className="mb-4 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="login-email" className="block text-sm font-medium text-gray-700 mb-1">
              E-Mail
            </label>
            <input
              id="login-email"
              autoComplete="username"
              type="email"
              required
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="name@beispiel.de"
            />
          </div>

          <div>
            <label htmlFor="login-password" className="block text-sm font-medium text-gray-700 mb-1">
              Passwort
            </label>
            <input
              type="password"
              id="login-password"
              autoComplete="current-password"
              required
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="Passwort"
            />
          </div>

          <button
            type="submit"
            disabled={loading}
            className="min-h-11 w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
          >
            {loading ? "Wird angemeldet…" : "Anmelden"}
          </button>
        </form>

        <p className="mt-4 text-center text-sm">
          <Link href="/forgot-password" className="text-gray-500 hover:text-blue-600 hover:underline">
            Passwort vergessen?
          </Link>
        </p>

        <p className="mt-3 text-center text-sm text-gray-500">
          Noch kein Konto?{" "}
          <Link href="/register" className="text-blue-600 hover:underline font-medium">
            Jetzt registrieren
          </Link>
        </p>
      </div>
    </div>
    <Footer />
    </div>
  );
}
