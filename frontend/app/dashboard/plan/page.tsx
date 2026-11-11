"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";
import { authApi, adminApi, billingApi, type ModuleRead, type CustomerRead } from "@/lib/api";
import { fetchModules, MODULE_KEYS } from "@/lib/modules";
import { Check, Lock } from "lucide-react";

const CATEGORY_LABELS: Record<string, string> = {
  ai: "KI-Features",
  core: "Core",
  analytics: "Analytics",
  integration: "Integrationen",
};

const MODULE_NAMES: Record<string, string> = {
  ai_cv_parser: "KI CV-Parser",
  ai_cover_letter: "KI Anschreiben",
  ai_interview_prep: "KI Interview-Vorbereitung",
  ai_linkedin_post: "KI LinkedIn-Posts",
  map_view: "Kartenansicht",
  job_scraper_import: "Job-Scraper Import",
  kanban_pipeline: "Kanban Pipeline",
  interview_scheduling: "Interview-Planung",
  analytics_advanced: "Analytics (Erweitert)",
  content_kit: "Content Kit",
  zeitarbeit_pool: "Zeitarbeiter-Pool",
  partner_portal: "Partner-Portal",
};

const PLAN_COLORS: Record<string, string> = {
  free: "bg-gray-100 text-gray-700",
  starter: "bg-blue-100 text-blue-700",
  professional: "bg-purple-100 text-purple-700",
  enterprise: "bg-amber-100 text-amber-700",
};

const STATUS_COLORS: Record<string, string> = {
  trial: "bg-yellow-100 text-yellow-700",
  active: "bg-green-100 text-green-700",
  suspended: "bg-orange-100 text-orange-700",
};

// Group module keys by category
const MODULE_CATEGORIES: Record<string, string[]> = {
  ai: [MODULE_KEYS.AI_CV_PARSER, MODULE_KEYS.AI_COVER_LETTER, MODULE_KEYS.AI_INTERVIEW_PREP, MODULE_KEYS.AI_LINKEDIN_POST],
  core: [MODULE_KEYS.KANBAN_PIPELINE, MODULE_KEYS.INTERVIEW_SCHEDULING, MODULE_KEYS.ZEITARBEIT_POOL],
  analytics: [MODULE_KEYS.ANALYTICS_ADVANCED],
  integration: [MODULE_KEYS.MAP_VIEW, MODULE_KEYS.JOB_SCRAPER_IMPORT, MODULE_KEYS.PARTNER_PORTAL, MODULE_KEYS.CONTENT_KIT],
};

const PLAN_ORDER = ["free", "starter", "professional", "enterprise"];

const PLAN_DESCRIPTIONS: Record<string, { label: string; price: string; description: string }> = {
  starter: { label: "Starter", price: "€49/Monat", description: "Für solo Recruiter – KI-Tools, Kanban, Analytics" },
  professional: { label: "Professional", price: "€149/Monat", description: "Für Teams – alle Module inkl. Zeitarbeit & Partner-Portal" },
  enterprise: { label: "Enterprise", price: "Auf Anfrage", description: "White-Label, Custom-Domain, dedizierter Support" },
};

export default function PlanPage() {
  const router = useRouter();
  const [customer, setCustomer] = useState<CustomerRead | null>(null);
  const [moduleDetails, setModuleDetails] = useState<ModuleRead[]>([]);
  const [activeModules, setActiveModules] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [checkoutLoading, setCheckoutLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [restricted, setRestricted] = useState(false);

  useEffect(() => {
    const token = auth.getToken();
    if (!token) { router.replace("/login"); return; }
    authApi.me(token).then(async (user) => {
    if (user.role !== "admin") {
      setRestricted(true);
      setLoading(false);
      return;
    }
    if (!user?.tenant_id) {
      // No tenant → show "no plan assigned" state
      setLoading(false);
      return;
    }

    await Promise.all([
      adminApi.getCustomer(token, user.tenant_id),
      adminApi.getModules(token, user.tenant_id),
      fetchModules(token),
    ])
      .then(([c, mods, active]) => {
        setCustomer(c);
        setModuleDetails(mods);
        setActiveModules(active);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
    }).catch(() => { setError("Arbeitsbereich konnte nicht geladen werden."); setLoading(false); });
  }, [router]);

  async function handleUpgrade(plan: string) {
    const token = auth.getToken();
    if (!token) return;
    setCheckoutLoading(plan);
    try {
      const { url } = await billingApi.createCheckout(token, plan);
      window.location.assign(url);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Checkout fehlgeschlagen.");
      setCheckoutLoading(null);
    }
  }

  async function handlePortal() {
    const token = auth.getToken();
    if (!token) return;
    setCheckoutLoading("portal");
    try {
      const { url } = await billingApi.openPortal(token);
      window.location.assign(url);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Portal nicht verfügbar.");
      setCheckoutLoading(null);
    }
  }

  if (restricted) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-8">
        <h1 className="text-xl font-bold text-gray-900">Planverwaltung</h1>
        <p role="alert" className="mt-4 rounded-xl border border-gray-200 bg-white p-5 text-gray-700">
          Nur Administratoren können den Plan und das Abonnement verwalten.
          Wenden Sie sich für Änderungen an Ihren Administrator.
        </p>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50">

        <div className="flex items-center justify-center h-96">
          <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full" />
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">

      <div className="max-w-3xl mx-auto px-4 py-8">
        <h1 className="text-xl font-bold text-gray-900 mb-6">Mein Plan</h1>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-4 text-red-700 text-sm">{error}</div>
        )}

        {/* Plan Info */}
        {customer ? (
          <div className="bg-white rounded-xl border border-gray-200 p-5 mb-6">
            <div className="flex items-start justify-between">
              <div>
                <h2 className="font-semibold text-gray-900 text-lg">{customer.name}</h2>
                <p className="text-sm text-gray-400">{customer.slug}</p>
              </div>
              <div className="flex gap-2">
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${PLAN_COLORS[customer.plan] ?? ""}`}>
                  {customer.plan}
                </span>
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_COLORS[customer.status] ?? ""}`}>
                  {customer.status}
                </span>
              </div>
            </div>
            <div className="flex gap-6 mt-4 text-sm text-gray-500">
              <span>{customer.user_count} User</span>
              <span>{customer.modules.length} / 12 Module aktiv</span>
              {customer.trial_ends_at && (
                <span>Trial bis: {new Date(customer.trial_ends_at).toLocaleDateString("de-DE")}</span>
              )}
            </div>
          </div>
        ) : (
          <div className="bg-amber-50 border border-amber-200 rounded-xl p-5 mb-6">
            <p className="font-medium text-amber-800">Kein Tenant zugewiesen</p>
            <p className="text-sm text-amber-600 mt-1">
              Ihr Account ist noch keiner Organisation zugeordnet. Wenden Sie sich an Ihren Administrator.
            </p>
          </div>
        )}

        {/* Upgrade CTAs */}
        {customer && (
          <div className="mb-6">
            <div className="flex items-center justify-between mb-3">
              <h2 className="font-semibold text-gray-900">Plan upgraden</h2>
              {customer.stripe_customer_id && (
                <button
                  onClick={handlePortal}
                  disabled={checkoutLoading === "portal"}
                  className="text-xs text-blue-600 hover:underline disabled:opacity-50"
                >
                  {checkoutLoading === "portal" ? "Wird geladen…" : "Abonnement verwalten"}
                </button>
              )}
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {(["starter", "professional", "enterprise"] as const).map((plan) => {
                const info = PLAN_DESCRIPTIONS[plan];
                const isCurrent = customer.plan === plan;
                const isDowngrade = PLAN_ORDER.indexOf(plan) < PLAN_ORDER.indexOf(customer.plan);
                return (
                  <div
                    key={plan}
                    className={`rounded-xl border p-4 flex flex-col gap-2 ${
                      isCurrent
                        ? "border-blue-300 bg-blue-50"
                        : "border-gray-200 bg-white"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-sm text-gray-800">{info.label}</span>
                      {isCurrent && (
                        <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded-full font-medium">
                          Aktuell
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500">{info.description}</p>
                    <p className="text-sm font-bold text-gray-900">{info.price}</p>
                    {!isCurrent && !isDowngrade && (
                      <button
                        onClick={() => handleUpgrade(plan)}
                        disabled={!!checkoutLoading}
                        className="mt-auto w-full rounded-lg bg-blue-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
                      >
                        {checkoutLoading === plan ? "Wird geöffnet…" : `Upgrade auf ${info.label}`}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Module Overview */}
        <div className="bg-white rounded-xl border border-gray-200 p-5">
          <h2 className="font-semibold text-gray-900 mb-5">Verfügbare Module</h2>
          <div className="space-y-6">
            {Object.entries(MODULE_CATEGORIES).map(([cat, keys]) => (
              <div key={cat}>
                <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                  {CATEGORY_LABELS[cat]}
                </h3>
                <div className="space-y-2">
                  {keys.map((key) => {
                    const active = activeModules.includes(key);
                    const detail = moduleDetails.find((m) => m.module_key === key);
                    return (
                      <div
                        key={key}
                        className={`flex items-center justify-between py-2.5 px-3 rounded-lg ${
                          active ? "bg-green-50" : "bg-gray-50 opacity-60"
                        }`}
                      >
                        <div>
                          <div className="flex items-center gap-2">
                            <span className={`text-sm font-medium ${active ? "text-gray-800" : "text-gray-400"}`}>
                              {active ? <Check size={13} className="inline text-green-600 mr-1" /> : <Lock size={13} className="inline text-gray-400 mr-1" />}{MODULE_NAMES[key] ?? key}
                            </span>
                          </div>
                          {detail && detail.usage_limit && (
                            <p className="text-xs text-gray-400 mt-0.5">
                              {detail.usage_current} / {detail.usage_limit} Aufrufe diesen Monat
                            </p>
                          )}
                        </div>
                        <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                          active ? "bg-green-100 text-green-700" : "bg-gray-200 text-gray-500"
                        }`}>
                          {active ? "Aktiv" : "Gesperrt"}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>

          {!customer && (
            <p className="text-xs text-center text-gray-400 mt-6 pt-4 border-t border-gray-100">
              Alle Module verfügbar (kein Tenant-Filter aktiv)
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
