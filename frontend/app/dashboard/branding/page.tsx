"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { BRAND } from "@/lib/brand";
import { brandingApi, brandTextColor, type WorkspaceBranding } from "@/lib/workspace-branding";
import { errorMessage } from "@/lib/workspace";

export default function BrandingPage() {
  const [saved, setSaved] = useState<WorkspaceBranding | null>(null);
  const [name, setName] = useState("");
  const [color, setColor] = useState("#2563eb");
  const [logo, setLogo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    const token = auth.getAccess();
    if (!token) return;
    let current = true;
    brandingApi.get(token).then(data => {
      if (current) { setSaved(data); setName(data.brand_name ?? ""); setColor(data.primary_color); setLogo(data.logo_url ?? ""); }
    }).catch(e => { if (current) setError(errorMessage(e)); });
    return () => { current = false; };
  }, []);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    const token = auth.getAccess();
    if (!token || !saved) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const data = await brandingApi.save(token, { brand_name: name.trim() || null, primary_color: color, logo_url: logo.trim() || null, version: saved.version });
      setSaved(data); window.dispatchEvent(new Event("palmscout-branding-changed"));
      setNotice("Markenauftritt gespeichert. Er gilt für deinen Arbeitsbereich und deine Karriereseite.");
    } catch (e) { setError(errorMessage(e)); }
    finally { setBusy(false); }
  }
  return <div className="mx-auto max-w-4xl space-y-6 px-4 py-8 sm:px-8">
    <header><p className="text-sm font-medium text-blue-700">Dein Unternehmen, dein Auftritt</p><h1 className="mt-2 text-3xl font-semibold">Markenauftritt</h1><p className="mt-3 text-sm leading-6 text-slate-600">Passe Namen, Logo und Farbe an. Der technische Anbieter bleibt {BRAND.company}.</p></header>
    {error && <p role="alert" className="rounded-xl bg-red-50 p-4 text-red-700">{error}</p>}
    {notice && <p role="status" className="rounded-xl bg-blue-50 p-4 text-blue-800">{notice}</p>}
    {!saved && !error && <p role="status">Markenauftritt wird geladen …</p>}
    {saved && <div className="grid gap-6 md:grid-cols-2">
      <form onSubmit={save} className="space-y-5 rounded-2xl border bg-white p-5">
        <fieldset disabled={busy || !saved.can_manage} className="space-y-5 disabled:opacity-60">
          <legend className="mb-4 font-semibold">Darstellung</legend>
          <label className="block text-sm">Anzeigename<input value={name} maxLength={80} onChange={e => setName(e.target.value)} placeholder={BRAND.product} className="mt-2 min-h-11 w-full rounded-xl border px-3" /></label>
          <label className="block text-sm">Markenfarbe<input type="color" value={color} onChange={e => setColor(e.target.value)} className="mt-2 block h-12 w-full rounded-xl border p-1" /></label>
          <label className="block text-sm">Logo-Adresse (HTTPS)<input type="url" value={logo} onChange={e => setLogo(e.target.value)} placeholder="https://…" maxLength={500} className="mt-2 min-h-11 w-full rounded-xl border px-3" /></label>
          <p className="text-xs leading-5 text-slate-600">Verwende ein Logo von deinem eigenen Webauftritt oder freigegebenen Bildspeicher. Eine leere Adresse entfernt das Logo.</p>
          <button className="min-h-11 rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white">Markenauftritt speichern</button>
        </fieldset>
        {!saved.can_manage && <p className="text-sm text-slate-600">Die Firmenadministration kann den Markenauftritt ändern.</p>}
      </form>
      <section aria-label="Markenvorschau" className="space-y-6 rounded-2xl border bg-white p-5">
        <h2 className="font-semibold">Vorschau</h2>
        <div className="space-y-5 rounded-xl border p-5" style={{ borderTop: `4px solid ${color}` }}>
          <p className="break-words text-xl font-bold">{name.trim() || BRAND.product}</p>
          <p className="text-sm text-slate-600">Gemeinsam den nächsten Schritt finden.</p>
          <span className="inline-flex min-h-11 items-center rounded-xl px-4 text-sm font-semibold" style={{ backgroundColor: color, color: brandTextColor(color) }}>Offene Stellen entdecken</span>
          <p className="text-xs text-slate-600">{BRAND.product} · {BRAND.company}</p>
        </div>
        <Link href={`/whitelabel/${saved.slug}`} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center text-sm font-medium text-blue-700">Gespeicherte Karriereseite öffnen ↗</Link>
        <p className="text-xs leading-5 text-slate-600">Eigene Domains werden nach Prüfung des Domainbesitzes und der TLS-Einrichtung durch neurofunken angebunden.</p>
      </section>
    </div>}
  </div>;
}
