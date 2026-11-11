"use client";

import { useEffect, useState } from "react";
import { useRouter, useParams } from "next/navigation";
import Link from "next/link";
import { auth } from "@/lib/auth";
import {
  adminApi,
  type CustomerRead,
  type ModuleRead,
  type ModuleCatalogEntry,
} from "@/lib/api";
import { User, Mail, Phone, MapPin } from "lucide-react";

const STATUS_COLORS: Record<string, string> = {
  trial: "bg-yellow-100 text-yellow-700",
  active: "bg-green-100 text-green-700",
  suspended: "bg-orange-100 text-orange-700",
  churned: "bg-red-100 text-red-700",
};

const PLAN_COLORS: Record<string, string> = {
  free: "bg-gray-100 text-gray-700",
  starter: "bg-blue-100 text-blue-700",
  professional: "bg-purple-100 text-purple-700",
  enterprise: "bg-amber-100 text-amber-700",
};

const CATEGORY_LABELS: Record<string, string> = {
  ai: "KI-Features",
  core: "Core",
  analytics: "Analytics",
  integration: "Integrationen",
};

// ── Branding Panel ──────────────────────────────────────────────────────────

function BrandingPanel({
  customer,
  colorInput,
  setColorInput,
  onSaveColor,
  onLogoUpload,
  onClearLogo,
  onSaveLogoUrl,
  saving,
  uploading,
}: {
  customer: CustomerRead | null;
  colorInput: string;
  setColorInput: (v: string) => void;
  onSaveColor: () => void;
  onLogoUpload: (f: File) => void;
  onClearLogo: () => void;
  onSaveLogoUrl: (url: string) => void;
  saving: boolean;
  uploading: boolean;
}) {
  const [logoUrlInput, setLogoUrlInput] = useState(customer?.logo_url ?? "");

  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 space-y-5">
      <h2 className="font-semibold text-gray-900 text-sm">Logo & Farbe</h2>

      {/* Live preview */}
      <div
        className="rounded-lg p-3 flex items-center gap-3"
        style={{ backgroundColor: colorInput }}
      >
        {customer?.logo_url ? (
          <img src={customer.logo_url} alt="Logo" className="h-7 w-auto rounded" />
        ) : (
          <div className="h-7 w-7 rounded bg-white/20 flex items-center justify-center text-white font-bold text-xs">
            {customer?.name.charAt(0).toUpperCase() ?? "?"}
          </div>
        )}
        <span className="text-white text-sm font-medium truncate">{customer?.name ?? "Vorschau"}</span>
      </div>

      {/* Primärfarbe */}
      <div>
        <label className="text-xs text-gray-500 block mb-2">Primärfarbe</label>
        <div className="flex items-center gap-2">
          <input
            type="color"
            value={colorInput}
            onChange={(e) => setColorInput(e.target.value)}
            className="h-9 w-14 rounded border border-gray-300 cursor-pointer p-0.5"
          />
          <input
            type="text"
            value={colorInput}
            onChange={(e) => setColorInput(e.target.value)}
            maxLength={7}
            className="flex-1 border border-gray-300 rounded px-2 py-1.5 text-sm font-mono"
            placeholder="#2563eb"
          />
          <button
            onClick={onSaveColor}
            disabled={saving}
            className="bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-xs px-3 py-2 rounded-lg transition-colors"
          >
            {saving ? "…" : "OK"}
          </button>
        </div>
      </div>

      {/* Logo Upload */}
      <div>
        <label className="text-xs text-gray-500 block mb-2">Logo hochladen</label>
        <label className="block cursor-pointer border-2 border-dashed border-gray-300 hover:border-blue-400 rounded-lg p-4 text-center transition-colors">
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp,image/svg+xml"
            className="hidden"
            disabled={uploading}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) onLogoUpload(file);
            }}
          />
          {uploading ? (
            <span className="text-xs text-blue-600">Hochladen…</span>
          ) : (
            <span className="text-xs text-gray-400">PNG / JPG / SVG · max. 5 MB · klicken oder ziehen</span>
          )}
        </label>
        {customer?.logo_url && (
          <div className="flex items-center gap-2 mt-2">
            <img src={customer.logo_url} alt="Logo" className="h-6 w-auto" />
            <button onClick={onClearLogo} disabled={saving} className="text-xs text-red-500 hover:text-red-700">
              Entfernen
            </button>
          </div>
        )}
      </div>

      {/* Fallback: manual URL */}
      <div>
        <label className="text-xs text-gray-500 block mb-2">Logo-URL (manuell)</label>
        <div className="flex gap-2">
          <input
            type="text"
            value={logoUrlInput}
            onChange={(e) => setLogoUrlInput(e.target.value)}
            placeholder="https://..."
            className="flex-1 border border-gray-300 rounded px-2 py-1.5 text-xs"
          />
          <button
            onClick={() => onSaveLogoUrl(logoUrlInput)}
            disabled={saving}
            className="bg-gray-700 hover:bg-gray-800 disabled:opacity-50 text-white text-xs px-3 py-2 rounded-lg"
          >
            {saving ? "…" : "OK"}
          </button>
        </div>
      </div>
    </div>
  );
}


export default function CustomerDetailPage() {
  const router = useRouter();
  const params = useParams();
  const id = params?.id as string;

  const [customer, setCustomer] = useState<CustomerRead | null>(null);
  const [modules, setModules] = useState<ModuleRead[]>([]);
  const [catalog, setCatalog] = useState<ModuleCatalogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [editForm, setEditForm] = useState<Partial<CustomerRead>>({});
  // White-label domain editing
  const [domainInput, setDomainInput] = useState("");
  const [domainSaving, setDomainSaving] = useState(false);
  // Branding (Sprint 2.8)
  const [colorInput, setColorInput] = useState("#2563eb");
  const [brandingSaving, setBrandingSaving] = useState(false);
  const [logoUploading, setLogoUploading] = useState(false);

  useEffect(() => {
    const token = auth.getToken();
    const user = auth.getUser();
    if (!token || user?.role !== "admin") {
      router.replace("/dashboard");
      return;
    }
    Promise.all([
      adminApi.getCustomer(token, id),
      adminApi.getModules(token, id),
      adminApi.getModuleCatalog(token),
    ])
      .then(([c, m, cat]) => {
        setCustomer(c);
        setModules(m);
        setCatalog(cat);
        setEditForm({ name: c.name, plan: c.plan, status: c.status, notes: c.notes ?? "" });
        setDomainInput(c.custom_domain ?? "");
        setColorInput(c.primary_color ?? "#2563eb");
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id, router]);

  async function handleSaveCustomer() {
    const token = auth.getToken();
    if (!token || !customer) return;
    setSaving("customer");
    try {
      const updated = await adminApi.updateCustomer(token, id, editForm);
      setCustomer(updated);
      setEditMode(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Fehler beim Speichern");
    } finally {
      setSaving(null);
    }
  }

  async function handleSaveDomain() {
    const token = auth.getToken();
    if (!token || !customer) return;
    setDomainSaving(true);
    setError(null);
    try {
      const updated = await adminApi.setCustomDomain(
        token,
        id,
        domainInput.trim() || null,
      );
      setCustomer(updated);
      setDomainInput(updated.custom_domain ?? "");
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Fehler beim Speichern der Domain");
    } finally {
      setDomainSaving(false);
    }
  }

  async function handleSaveColor() {
    const token = auth.getToken();
    if (!token || !customer) return;
    setBrandingSaving(true);
    setError(null);
    try {
      const updated = await adminApi.updateBranding(token, id, { primary_color: colorInput });
      setCustomer(updated);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Fehler beim Speichern der Farbe");
    } finally {
      setBrandingSaving(false);
    }
  }

  async function handleLogoUpload(file: File) {
    const token = auth.getToken();
    if (!token || !customer) return;
    setLogoUploading(true);
    setError(null);
    try {
      const { upload_url, logo_url } = await adminApi.getLogoUploadUrl(token, id, file.type);
      // Upload directly to S3/R2
      const uploadRes = await fetch(upload_url, {
        method: "PUT",
        headers: { "Content-Type": file.type },
        body: file,
      });
      if (!uploadRes.ok) throw new Error("Upload fehlgeschlagen");
      // Save the logo URL on the customer
      const updated = await adminApi.updateBranding(token, id, { logo_url });
      setCustomer(updated);
    } catch (e: unknown) {
      // Fallback: if S3 not configured (503), let admin enter URL manually
      const msg = e instanceof Error ? e.message : "Upload fehlgeschlagen";
      setError(msg.includes("S3/R2") ? msg + " Bitte URL manuell eintragen." : msg);
    } finally {
      setLogoUploading(false);
    }
  }

  async function handleClearLogo() {
    const token = auth.getToken();
    if (!token || !customer) return;
    setBrandingSaving(true);
    try {
      const updated = await adminApi.updateBranding(token, id, { logo_url: "__clear__" });
      setCustomer(updated);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Fehler");
    } finally {
      setBrandingSaving(false);
    }
  }

  async function handleSaveLogoUrl(url: string) {
    const token = auth.getToken();
    if (!token || !customer) return;
    setBrandingSaving(true);
    try {
      const updated = await adminApi.updateBranding(token, id, { logo_url: url || "__clear__" });
      setCustomer(updated);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Fehler");
    } finally {
      setBrandingSaving(false);
    }
  }

  async function handleToggleModule(moduleKey: string, enabled: boolean) {
    const token = auth.getToken();
    if (!token) return;
    setSaving(moduleKey);
    try {
      const updated = await adminApi.toggleModule(token, id, moduleKey, { enabled });
      setModules((prev) => {
        const idx = prev.findIndex((m) => m.module_key === moduleKey);
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = updated;
          return next;
        }
        return [...prev, updated];
      });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Fehler");
    } finally {
      setSaving(null);
    }
  }

  function getModuleState(key: string): boolean {
    const m = modules.find((m) => m.module_key === key);
    return m?.enabled ?? false;
  }

  // Group catalog by category
  const byCategory = catalog.reduce<Record<string, ModuleCatalogEntry[]>>((acc, m) => {
    acc[m.category] = acc[m.category] ?? [];
    acc[m.category].push(m);
    return acc;
  }, {});

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50">

        <div className="flex items-center justify-center h-96">
          <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full" />
        </div>
      </div>
    );
  }

  if (!customer) {
    return (
      <div className="min-h-screen bg-gray-50">

        <div className="max-w-2xl mx-auto px-4 py-16 text-center">
          <p className="text-gray-500">Kunde nicht gefunden.</p>
          <Link href="/admin" className="text-blue-600 mt-4 inline-block">← Admin Hub</Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">

      <div className="max-w-5xl mx-auto px-4 py-8">
        {/* Breadcrumb */}
        <div className="flex items-center gap-3 mb-6 text-sm">
          <Link href="/admin" className="text-gray-400 hover:text-gray-600">Admin Hub</Link>
          <span className="text-gray-300">/</span>
          <span className="text-gray-600">{customer.name}</span>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-4 text-red-700 text-sm">
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
          {/* Left: Customer Info */}
          <div className="lg:col-span-1 space-y-4">
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <div className="flex items-start justify-between mb-4">
                <div>
                  <h1 className="text-lg font-semibold text-gray-900">{customer.name}</h1>
                  <p className="text-xs text-gray-400 font-mono">{customer.slug}</p>
                </div>
                <button
                  onClick={() => setEditMode(!editMode)}
                  className="text-xs text-blue-600 hover:text-blue-700"
                >
                  {editMode ? "Abbrechen" : "Bearbeiten"}
                </button>
              </div>

              {!editMode ? (
                <div className="space-y-3 text-sm">
                  <div className="flex gap-2">
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${STATUS_COLORS[customer.status]}`}>
                      {customer.status}
                    </span>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${PLAN_COLORS[customer.plan]}`}>
                      {customer.plan}
                    </span>
                  </div>
                  <div className="text-gray-500 space-y-1">
                    {customer.contact_name && <p className="flex items-center gap-1.5"><User size={12} className="text-gray-400" />{customer.contact_name}</p>}
                    {customer.contact_email && <p className="flex items-center gap-1.5"><Mail size={12} className="text-gray-400" />{customer.contact_email}</p>}
                    {customer.phone && <p className="flex items-center gap-1.5"><Phone size={12} className="text-gray-400" />{customer.phone}</p>}
                    {customer.city && <p className="flex items-center gap-1.5"><MapPin size={12} className="text-gray-400" />{customer.city}, {customer.country}</p>}
                  </div>
                  {customer.notes && (
                    <p className="text-xs text-gray-400 bg-gray-50 rounded p-2 mt-2">{customer.notes}</p>
                  )}
                  <div className="pt-2 border-t border-gray-100 text-xs text-gray-400">
                    <p>{customer.user_count} User · {customer.modules.length} Module aktiv</p>
                    <p>Erstellt: {new Date(customer.created_at).toLocaleDateString("de-DE")}</p>
                  </div>
                </div>
              ) : (
                <div className="space-y-3">
                  <div>
                    <label className="text-xs text-gray-500 block mb-1">Name</label>
                    <input
                      value={editForm.name ?? ""}
                      onChange={(e) => setEditForm((f) => ({ ...f, name: e.target.value }))}
                      className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-gray-500 block mb-1">Plan</label>
                    <select
                      value={editForm.plan ?? "starter"}
                      onChange={(e) => setEditForm((f) => ({ ...f, plan: e.target.value as CustomerRead["plan"] }))}
                      className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                    >
                      {["free", "starter", "professional", "enterprise"].map((p) => (
                        <option key={p} value={p}>{p}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-gray-500 block mb-1">Status</label>
                    <select
                      value={editForm.status ?? "trial"}
                      onChange={(e) => setEditForm((f) => ({ ...f, status: e.target.value as CustomerRead["status"] }))}
                      className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm"
                    >
                      {["trial", "active", "suspended", "churned"].map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-gray-500 block mb-1">Notizen</label>
                    <textarea
                      value={editForm.notes ?? ""}
                      onChange={(e) => setEditForm((f) => ({ ...f, notes: e.target.value }))}
                      rows={3}
                      className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm resize-none"
                    />
                  </div>
                  <button
                    onClick={handleSaveCustomer}
                    disabled={saving === "customer"}
                    className="w-full bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm py-2 rounded-lg transition-colors"
                  >
                    {saving === "customer" ? "Speichern..." : "Speichern"}
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* White-Label Branding */}
          <div className="lg:col-span-1 space-y-4">
            {/* Custom Domain */}
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <h2 className="font-semibold text-gray-900 mb-4 text-sm">Custom Domain</h2>
              <div className="space-y-3">
                <div>
                  <input
                    type="text"
                    placeholder="z.B. recruit.firma.de"
                    value={domainInput}
                    onChange={(e) => setDomainInput(e.target.value)}
                    className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm font-mono"
                  />
                  <p className="text-[11px] text-gray-400 mt-1">
                    DNS-Ziel wird durch neurofunken bereitgestellt · leer = entfernen
                  </p>
                </div>
                {customer?.custom_domain && (
                  <div className="flex items-center gap-2 text-xs text-green-700 bg-green-50 rounded px-2 py-1.5">
                    <span className="font-mono truncate flex-1">{customer.custom_domain}</span>
                    <a href={`/whitelabel/${customer.slug}`} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline whitespace-nowrap">
                      Vorschau →
                    </a>
                  </div>
                )}
                <button onClick={handleSaveDomain} disabled={domainSaving}
                  className="w-full bg-gray-900 hover:bg-gray-800 disabled:opacity-50 text-white text-sm py-2 rounded-lg transition-colors">
                  {domainSaving ? "Speichern..." : "Domain speichern"}
                </button>
              </div>
            </div>

            {/* Logo + Primärfarbe */}
            <BrandingPanel
              customer={customer}
              colorInput={colorInput}
              setColorInput={setColorInput}
              onSaveColor={handleSaveColor}
              onLogoUpload={handleLogoUpload}
              onClearLogo={handleClearLogo}
              onSaveLogoUrl={handleSaveLogoUrl}
              saving={brandingSaving}
              uploading={logoUploading}
            />
          </div>

          {/* Right: Module Matrix */}
          <div className="lg:col-span-2 lg:col-start-3">
            <div className="bg-white rounded-xl border border-gray-200 p-5">
              <h2 className="font-semibold text-gray-900 mb-5">Module-Konfiguration</h2>
              <div className="space-y-6">
                {Object.entries(byCategory).map(([cat, entries]) => (
                  <div key={cat}>
                    <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
                      {CATEGORY_LABELS[cat] ?? cat}
                    </h3>
                    <div className="space-y-2">
                      {entries.map((entry) => {
                        const enabled = getModuleState(entry.key);
                        const isSaving = saving === entry.key;
                        const mod = modules.find((m) => m.module_key === entry.key);
                        return (
                          <div
                            key={entry.key}
                            className="flex items-center justify-between py-2.5 px-3 rounded-lg bg-gray-50 hover:bg-gray-100 transition-colors"
                          >
                            <div>
                              <p className="text-sm font-medium text-gray-800">{entry.name}</p>
                              <p className="text-xs text-gray-400 font-mono">{entry.key}</p>
                              {mod && mod.usage_limit && (
                                <p className="text-xs text-blue-500 mt-0.5">
                                  {mod.usage_current} / {mod.usage_limit} Calls
                                </p>
                              )}
                            </div>
                            <button
                              onClick={() => handleToggleModule(entry.key, !enabled)}
                              disabled={isSaving}
                              className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none disabled:opacity-50 ${
                                enabled ? "bg-blue-600" : "bg-gray-300"
                              }`}
                            >
                              <span
                                className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                                  enabled ? "translate-x-6" : "translate-x-1"
                                }`}
                              />
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
