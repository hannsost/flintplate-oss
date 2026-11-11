"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { authApi, companyApi, ApiError } from "@/lib/api";
import { auth } from "@/lib/auth";
import { Navbar } from "@/components/layout/Navbar";
import { Footer } from "@/components/layout/Footer";

type Step = "account" | "company";

export default function RecruiterRegisterPage() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("account");

  const [account, setAccount] = useState({ full_name: "", email: "", password: "" });
  const [termsAccepted, setTermsAccepted] = useState(false);
  const [company, setCompany] = useState({ name: "", website: "", location: "", description: "" });
  const [workspaceType, setWorkspaceType] = useState<"internal_hr" | "recruiter_agency" | "solo_recruiter" | "zeitarbeit">("internal_hr");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) return;
    authApi.me(token).then(user => {
      if (user.company_id && user.tenant_id) router.replace("/dashboard");
      else if (user.role === "candidate" || user.role === "recruiter") setStep("company");
    }).catch(() => {});
  }, [router]);

  async function handleAccountSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!termsAccepted) {
      setError("Bitte akzeptiere die Nutzungsbedingungen.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const tokens = await authApi.register(account);
      auth.setTokens(tokens.access_token, tokens.refresh_token);
      await authApi.updateConsent(tokens.access_token, { terms_accepted: true, ai_opt_in: false });
      setStep("company");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Registrierung fehlgeschlagen.");
    } finally {
      setLoading(false);
    }
  }

  async function handleCompanySubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const token = auth.getAccess();
      if (!token) throw new Error("Not authenticated");
      if (!termsAccepted) throw new ApiError(422, "Bitte akzeptiere die Nutzungsbedingungen.");
      const consent = await authApi.getConsent(token);
      await authApi.updateConsent(token, { terms_accepted: true, ai_opt_in: consent?.ai_opt_in ?? false });
      await companyApi.create(token, {
        name: company.name,
        workspace_type: workspaceType,
        website: company.website || undefined,
        location: company.location || undefined,
        description: company.description || undefined,
      });
      // Company creation changes role and tenant. Replace the registration
      // token before navigating so all guards see the new workspace.
      const refresh = auth.getRefresh();
      if (refresh) {
        const tokens = await authApi.refresh(refresh);
        auth.setTokens(tokens.access_token, tokens.refresh_token);
      }
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Unternehmen konnte nicht angelegt werden.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
    <Navbar />
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4 py-8">
      <div className="w-full max-w-md bg-white rounded-2xl shadow p-8">
        {/* Header */}
        <div className="mb-6">
          <Link href="/" className="text-lg font-bold tracking-tight">
            palm<span className="text-blue-600">scout</span>
          </Link>
          <h1 className="text-2xl font-bold text-gray-900 mt-3">Dein Recruiting-Arbeitsbereich</h1>
          <p className="text-sm text-gray-500 mt-1">
            {step === "account"
              ? "Erstelle dein persönliches Konto"
              : "Richte dein Unternehmen ein"}
          </p>
        </div>

        {/* Step indicator */}
        <div className="flex items-center gap-2 mb-6">
          {(["account", "company"] as Step[]).map((s, i) => {
            const done = step === "company" && s === "account";
            const active = step === s;
            return (
              <div key={s} className="flex items-center gap-2">
                <div className={[
                  "flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold",
                  done ? "bg-blue-600 text-white" :
                  active ? "bg-blue-600 text-white ring-2 ring-blue-200" :
                  "bg-gray-200 text-gray-500",
                ].join(" ")}>
                  {done ? "✓" : i + 1}
                </div>
                <span className={`text-sm ${active ? "font-medium text-gray-900" : "text-gray-400"}`}>
                  {s === "account" ? "Konto" : "Unternehmen"}
                </span>
                {i === 0 && <div className={`h-px w-8 ${done ? "bg-blue-600" : "bg-gray-200"}`} />}
              </div>
            );
          })}
        </div>

        {error && (
          <div role="alert" className="mb-4 rounded-lg bg-red-50 border border-red-200 p-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* Step 1: Account */}
        {step === "account" && (
          <form onSubmit={handleAccountSubmit} className="space-y-4">
            <div>
              <label htmlFor="onboarding-field-0" className="block text-sm font-medium text-gray-700 mb-1">Name</label>
              <input id="onboarding-field-0"
                type="text"
                required
                value={account.full_name}
                onChange={(e) => setAccount({ ...account, full_name: e.target.value })}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Max Mustermann"
              />
            </div>
            <div>
              <label htmlFor="onboarding-field-1" className="block text-sm font-medium text-gray-700 mb-1">E-Mail</label>
              <input id="onboarding-field-1"
                type="email"
                required
                value={account.email}
                onChange={(e) => setAccount({ ...account, email: e.target.value })}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="max@unternehmen.de"
              />
            </div>
            <div>
              <label htmlFor="onboarding-field-2" className="block text-sm font-medium text-gray-700 mb-1">Passwort</label>
              <input id="onboarding-field-2"
                type="password"
                required
                minLength={8}
                value={account.password}
                onChange={(e) => setAccount({ ...account, password: e.target.value })}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Mindestens 8 Zeichen"
              />
            </div>
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
                <Link href="/legal/agb-b2b" target="_blank" className="text-blue-600 hover:underline">AGB</Link>
                {" "}und{" "}
                <Link href="/legal/datenschutz" target="_blank" className="text-blue-600 hover:underline">Datenschutzrichtlinie</Link>
                . *
              </span>
            </label>
            <button
              type="submit"
              disabled={loading}
              className="min-h-11 w-full rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60 transition-colors"
            >
              {loading ? "Wird erstellt…" : "Weiter →"}
            </button>
          </form>
        )}

        {/* Step 2: Company */}
        {step === "company" && (
          <form onSubmit={handleCompanySubmit} className="space-y-4">
            <div>
              <label htmlFor="workspace-type" className="block text-sm font-medium text-gray-700 mb-1">Wie arbeitet dein Team?</label>
              <select id="workspace-type" value={workspaceType}
                onChange={(event) => setWorkspaceType(event.target.value as typeof workspaceType)}
                className="min-h-11 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm">
                <option value="internal_hr">HR-Abteilung im Unternehmen</option>
                <option value="recruiter_agency">Personalberatung / Headhunting-Agentur</option>
                <option value="solo_recruiter">Selbstständiger Headhunter</option>
                <option value="zeitarbeit">Zeitarbeitsfirma</option>
              </select>
              <p className="mt-2 text-xs text-gray-500">Du erhältst einen eigenen Arbeitsbereich mit 14 Tagen zum Ausprobieren. Es entsteht kein kostenpflichtiges Abonnement.</p>
            </div>
            <div>
              <label htmlFor="onboarding-field-3" className="block text-sm font-medium text-gray-700 mb-1">Unternehmensname *</label>
              <input id="onboarding-field-3"
                type="text"
                required
                value={company.name}
                onChange={(e) => setCompany({ ...company, name: e.target.value })}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="Acme GmbH"
              />
            </div>
            <div>
              <label htmlFor="onboarding-field-4" className="block text-sm font-medium text-gray-700 mb-1">Website</label>
              <input id="onboarding-field-4"
                type="url"
                value={company.website}
                onChange={(e) => setCompany({ ...company, website: e.target.value })}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="https://acme.de"
              />
            </div>
            <div>
              <label htmlFor="onboarding-field-5" className="block text-sm font-medium text-gray-700 mb-1">Standort</label>
              <input id="onboarding-field-5"
                type="text"
                value={company.location}
                onChange={(e) => setCompany({ ...company, location: e.target.value })}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="München"
              />
            </div>
            <div>
              <label htmlFor="onboarding-field-6" className="block text-sm font-medium text-gray-700 mb-1">Kurzbeschreibung</label>
              <textarea id="onboarding-field-6"
                rows={3}
                value={company.description}
                onChange={(e) => setCompany({ ...company, description: e.target.value })}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                placeholder="Wir sind ein innovatives Unternehmen…"
              />
            </div>
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
                <Link href="/legal/agb-b2b" target="_blank" className="text-blue-600 hover:underline">AGB</Link>
                {" "}und{" "}
                <Link href="/legal/datenschutz" target="_blank" className="text-blue-600 hover:underline">Datenschutzrichtlinie</Link>
                . *
              </span>
            </label>
            <button
              type="submit"
              disabled={loading}
              className="min-h-11 w-full rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-60 transition-colors"
            >
              {loading ? "Wird angelegt…" : "Dashboard öffnen →"}
            </button>
          </form>
        )}

        <p className="mt-6 text-center text-sm text-gray-500">
          Kandidat statt Recruiter?{" "}
          <Link href="/register" className="text-blue-600 hover:underline font-medium">
            Kandidaten-Konto erstellen
          </Link>
        </p>
        <p className="mt-2 text-center text-sm text-gray-500">
          Bereits registriert?{" "}
          <Link href="/login" className="text-blue-600 hover:underline font-medium">
            Einloggen
          </Link>
        </p>
      </div>
    </div>
    <Footer />
    </>
  );
}
