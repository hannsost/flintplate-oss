"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { companyApi, authApi, ApiError } from "@/lib/api";
import type { CompanyRead } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function DashboardSettingsPage() {
  const router = useRouter();
  const [company, setCompany] = useState<CompanyRead | null>(null);
  const [form, setForm] = useState({ name: "", website: "", location: "", description: "", logo_url: "" });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const token = auth.getAccess();
    if (!token) { router.replace("/login"); return; }
    try {
      const user = await authApi.me(token);
      if (user.role !== "recruiter") { router.replace("/profile"); return; }
      const c = await companyApi.getMine(token);
      setCompany(c);
      setForm({
        name: c.name,
        website: c.website ?? "",
        location: c.location ?? "",
        description: c.description ?? "",
        logo_url: c.logo_url ?? "",
      });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else if (e instanceof ApiError && e.status === 404) {
        // No company yet – redirect to create flow
        router.replace("/register/recruiter");
      } else setError("Fehler beim Laden.");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => { load(); }, [load]);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    const token = auth.getAccess();
    if (!token) return;
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const updated = await companyApi.updateMine(token, {
        name: form.name || undefined,
        website: form.website || undefined,
        location: form.location || undefined,
        description: form.description || undefined,
        logo_url: form.logo_url || undefined,
      });
      setCompany(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Speichern fehlgeschlagen.");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <>

        <div className="flex min-h-[60vh] items-center justify-center">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      </>
    );
  }

  return (
    <>

      <main className="mx-auto max-w-2xl px-4 py-8 space-y-6">
        <div className="flex items-center gap-3">
          <Link href="/dashboard" className="text-sm text-gray-500 hover:text-gray-700">
            ← Dashboard
          </Link>
          <h1 className="text-xl font-bold text-gray-900">Unternehmens-Einstellungen</h1>
        </div>

        {error && (
          <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Unternehmensprofil</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSave} className="space-y-4">
              <div>
                <Label htmlFor="name">Unternehmensname *</Label>
                <Input
                  id="name"
                  required
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  placeholder="Acme GmbH"
                />
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <Label htmlFor="website">Website</Label>
                  <Input
                    id="website"
                    type="url"
                    value={form.website}
                    onChange={(e) => setForm({ ...form, website: e.target.value })}
                    placeholder="https://acme.de"
                  />
                </div>
                <div>
                  <Label htmlFor="location">Standort</Label>
                  <Input
                    id="location"
                    value={form.location}
                    onChange={(e) => setForm({ ...form, location: e.target.value })}
                    placeholder="München"
                  />
                </div>
              </div>

              <div>
                <Label htmlFor="logo_url">Logo-URL</Label>
                <Input
                  id="logo_url"
                  type="url"
                  value={form.logo_url}
                  onChange={(e) => setForm({ ...form, logo_url: e.target.value })}
                  placeholder="https://cdn.acme.de/logo.png"
                />
                {form.logo_url && (
                  <div className="mt-2">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img
                      src={form.logo_url}
                      alt="Logo-Vorschau"
                      className="h-12 w-auto rounded border border-gray-200 object-contain p-1"
                      onError={(e) => { (e.target as HTMLImageElement).style.display = "none"; }}
                    />
                  </div>
                )}
              </div>

              <div>
                <Label htmlFor="description">Unternehmensbeschreibung</Label>
                <Textarea
                  id="description"
                  rows={4}
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  placeholder="Kurze Beschreibung eures Unternehmens für Kandidaten…"
                />
                <p className="text-xs text-gray-400 mt-1">Wird auf Stellenanzeigen angezeigt</p>
              </div>

              <div className="flex items-center gap-3 pt-1">
                <Button type="submit" disabled={saving}>
                  {saving ? "Wird gespeichert…" : "Änderungen speichern"}
                </Button>
                {saved && <span className="text-sm text-blue-600 font-medium">✓ Gespeichert!</span>}
              </div>
            </form>
          </CardContent>
        </Card>

        {company && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base text-gray-500">Unternehmen-ID</CardTitle>
            </CardHeader>
            <CardContent>
              <p className="font-mono text-xs text-gray-400 break-all">{company.id}</p>
              <p className="text-xs text-gray-400 mt-1">
                Erstellt am {new Date(company.created_at).toLocaleDateString("de-DE")}
              </p>
            </CardContent>
          </Card>
        )}
      </main>
    </>
  );
}
