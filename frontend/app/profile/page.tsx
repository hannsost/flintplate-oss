"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";
import { profileApi, aiApi, authApi, ApiError } from "@/lib/api";
import type { ProfileRead, Skill, ParseCVResponse } from "@/lib/api";
import { Navbar } from "@/components/layout/Navbar";
import { Sidebar } from "@/components/layout/Sidebar";
import { CVDropzone } from "@/components/profile/CVDropzone";
import { ParsedCVPreview } from "@/components/profile/ParsedCVPreview";
import { ExportButtons } from "@/components/profile/ExportButtons";
import { SkillGapWidget } from "@/components/profile/SkillGapWidget";
import { AvailabilityWidget } from "@/components/profile/AvailabilityWidget";
import type { AppliedData } from "@/components/profile/ParsedCVPreview";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";

// ── Types ─────────────────────────────────────────────────────────────────────

type SkillDraft = Omit<Skill, "id" | "profile_id" | "source" | "created_at">;

const LEVELS = ["beginner", "intermediate", "advanced", "expert"] as const;

// ── Step indicator ────────────────────────────────────────────────────────────

function Steps({ current }: { current: number }) {
  const steps = ["Basisdaten", "Kenntnisse", "Lebenslauf"];
  return (
    <div className="flex items-center gap-2 mb-8">
      {steps.map((label, i) => {
        const n = i + 1;
        const done = n < current;
        const active = n === current;
        return (
          <div key={n} className="flex items-center gap-2">
            <div
              className={[
                "flex h-7 w-7 items-center justify-center rounded-full text-xs font-semibold",
                done ? "bg-blue-600 text-white" :
                active ? "bg-blue-600 text-white ring-2 ring-blue-200" :
                "bg-gray-200 text-gray-500",
              ].join(" ")}
            >
              {done ? "✓" : n}
            </div>
            <span className={`text-sm ${active ? "font-medium text-gray-900" : "text-gray-400"}`}>
              {label}
            </span>
            {i < steps.length - 1 && (
              <div className={`h-px w-8 ${done ? "bg-blue-600" : "bg-gray-200"}`} />
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Step 1: Basic Info ────────────────────────────────────────────────────────

function StepBasicInfo({
  profile,
  onSave,
}: {
  profile: ProfileRead;
  onSave: (data: Partial<ProfileRead>) => Promise<void>;
}) {
  const [form, setForm] = useState({
    headline: profile.headline ?? "",
    summary: profile.summary ?? "",
    location: profile.location ?? "",
    phone: profile.phone ?? "",
    website: profile.website ?? "",
    linkedin_url: profile.linkedin_url ?? "",
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSave(form);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Speichern fehlgeschlagen.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <div>
        <Label htmlFor="headline">Berufsbezeichnung</Label>
        <Input
          id="headline"
          value={form.headline}
          onChange={(e) => setForm({ ...form, headline: e.target.value })}
          placeholder="z.B. Senior Python Engineer"
          className="mt-1"
        />
      </div>

      <div>
        <Label htmlFor="summary">Über mich</Label>
        <Textarea
          id="summary"
          value={form.summary}
          onChange={(e) => setForm({ ...form, summary: e.target.value })}
          placeholder="Kurze Beschreibung deiner Person und deiner Ziele…"
          rows={4}
          className="mt-1"
        />
      </div>

      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
        <div>
          <Label htmlFor="location">Standort</Label>
          <Input
            id="location"
            value={form.location}
            onChange={(e) => setForm({ ...form, location: e.target.value })}
            placeholder="z.B. Berlin"
            className="mt-1"
          />
        </div>
        <div>
          <Label htmlFor="phone">Telefon</Label>
          <Input
            id="phone"
            type="tel"
            value={form.phone}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
            placeholder="+49 30 12345678"
            className="mt-1"
          />
        </div>
        <div>
          <Label htmlFor="website">Website</Label>
          <Input
            id="website"
            type="url"
            value={form.website}
            onChange={(e) => setForm({ ...form, website: e.target.value })}
            placeholder="https://meinportfolio.de"
            className="mt-1"
          />
        </div>
        <div>
          <Label htmlFor="linkedin">LinkedIn</Label>
          <Input
            id="linkedin"
            type="url"
            value={form.linkedin_url}
            onChange={(e) => setForm({ ...form, linkedin_url: e.target.value })}
            placeholder="https://linkedin.com/in/..."
            className="mt-1"
          />
        </div>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      <Button type="submit" disabled={saving}>
        {saving ? "Wird gespeichert…" : "Weiter →"}
      </Button>
    </form>
  );
}

// ── Step 2: Skills ────────────────────────────────────────────────────────────

function StepSkills({
  profile,
  onSave,
}: {
  profile: ProfileRead;
  onSave: (skills: SkillDraft[]) => Promise<void>;
}) {
  const [skills, setSkills] = useState<SkillDraft[]>(
    profile.skills.length > 0
      ? profile.skills.map(({ name, category, level, years_of_experience }) => ({
          name, category, level, years_of_experience,
        }))
      : [{ name: "", category: null, level: null, years_of_experience: null }],
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function addSkill() {
    setSkills([...skills, { name: "", category: null, level: null, years_of_experience: null }]);
  }

  function removeSkill(i: number) {
    setSkills(skills.filter((_, idx) => idx !== i));
  }

  function updateSkill(i: number, patch: Partial<SkillDraft>) {
    setSkills(skills.map((s, idx) => (idx === i ? { ...s, ...patch } : s)));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSave(skills.filter((s) => s.name.trim() !== ""));
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : "Speichern fehlgeschlagen.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <p className="text-sm text-gray-500">
        Füge deine Kenntnisse und Technologien hinzu.
      </p>

      {skills.map((skill, i) => (
        <div key={i} className="flex flex-wrap items-end gap-3 rounded-lg border border-gray-200 p-3">
          <div className="flex-1 min-w-[160px]">
            <Label className="text-xs">Kenntnisname *</Label>
            <Input
              value={skill.name}
              onChange={(e) => updateSkill(i, { name: e.target.value })}
              placeholder="z.B. Python"
              className="mt-1 h-8 text-sm"
            />
          </div>
          <div className="w-36">
            <Label className="text-xs">Level</Label>
            <select
              value={skill.level ?? ""}
              onChange={(e) => updateSkill(i, { level: e.target.value as SkillDraft["level"] || null })}
              className="mt-1 h-8 w-full rounded-md border border-input bg-background px-2 text-sm"
            >
              <option value="">–</option>
              {LEVELS.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
          </div>
          <div className="w-24">
            <Label className="text-xs">Jahre</Label>
            <Input
              type="number"
              min={0}
              max={50}
              value={skill.years_of_experience ?? ""}
              onChange={(e) => updateSkill(i, {
                years_of_experience: e.target.value ? Number(e.target.value) : null,
              })}
              className="mt-1 h-8 text-sm"
            />
          </div>
          <button
            type="button"
            onClick={() => removeSkill(i)}
            className="mb-0.5 text-gray-400 hover:text-red-500 transition-colors text-lg leading-none"
            aria-label="Entfernen"
          >
            ×
          </button>
        </div>
      ))}

      <Button type="button" variant="outline" size="sm" onClick={addSkill}>
        + Kenntniss hinzufügen
      </Button>

      <Separator />

      {error && <p className="text-sm text-red-600">{error}</p>}

      <Button type="submit" disabled={saving}>
        {saving ? "Wird gespeichert…" : "Weiter →"}
      </Button>
    </form>
  );
}

// ── Step 3: CV Upload + KI-Vorschau ──────────────────────────────────────────

function StepCV({
  profile,
  token,
  onDone,
}: {
  profile: ProfileRead;
  token: string;
  onDone: (updatedProfile: ProfileRead, fields: Record<string, unknown>) => void;
}) {
  const [parseResult, setParseResult] = useState<ParseCVResponse | null>(null);
  const [cvFilename, setCvFilename] = useState<string | null>(profile.cv_original_filename);
  const [applying, setApplying] = useState(false);
  const [applyError, setApplyError] = useState<string | null>(null);

  async function handleUpload(file: File) {
    // Use the full Sprint 0.3 AI parser endpoint
    const result = await aiApi.parseCv(token, file);
    setCvFilename(file.name);
    setParseResult(result);
  }

  async function handleApply(data: AppliedData) {
    setApplying(true);
    setApplyError(null);
    try {
      const updated = await profileApi.update(token, profile.id, {
        headline: data.headline,
        location: data.location,
        phone: data.phone,
        skills: data.skills,
        work_experiences: data.work_experiences,
        educations: data.educations,
      });
      onDone(updated, parseResult?.structured_data ?? {});
    } catch (err) {
      setApplyError(err instanceof ApiError ? err.detail : "Fehler beim Speichern.");
    } finally {
      setApplying(false);
    }
  }

  return (
    <div className="space-y-5">
      <CVDropzone onUpload={handleUpload} currentFilename={cvFilename} />

      {parseResult && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-gray-700">
              KI-Extraktion – Vorschau &amp; Bearbeiten
            </CardTitle>
          </CardHeader>
          <CardContent>
            {applying ? (
              <p className="text-sm text-blue-600 animate-pulse">Wird gespeichert…</p>
            ) : (
              <ParsedCVPreview result={parseResult} onApply={handleApply} />
            )}
            {applyError && <p className="mt-2 text-xs text-red-600">{applyError}</p>}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ProfilePage() {
  const router = useRouter();
  const [profile, setProfile] = useState<ProfileRead | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [step, setStep] = useState(1);
  const [done, setDone] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    const t = auth.getAccess();
    if (!t) { router.replace("/login"); return; }
    setToken(t);

    // Workers use the worker portal, not the candidate profile page
    authApi.me(t).then((u) => {
      if (u.role === "worker") router.replace("/worker");
    }).catch(() => {});

    profileApi.getMe(t)
      .then(setProfile)
      .catch((err) => {
        if (err?.status === 401) {
          auth.clear();
          router.replace("/login");
        } else {
          setLoadError("Profil konnte nicht geladen werden.");
        }
      });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // run once on mount only

  async function handleBasicInfo(data: Partial<ProfileRead>) {
    if (!token || !profile) return;
    const updated = await profileApi.update(token, profile.id, data);
    setProfile(updated);
    setStep(2);
  }

  async function handleSkills(skills: SkillDraft[]) {
    if (!token || !profile) return;
    const updated = await profileApi.update(token, profile.id, { skills });
    setProfile(updated);
    setStep(3);
  }

  function handleCVDone(updatedProfile: ProfileRead) {
    setProfile(updatedProfile);
    setDone(true);
  }

  // ── Loading ──────────────────────────────────────────────────────────────────
  if (loadError) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-red-600">{loadError}</p>
      </div>
    );
  }

  if (!profile || !token) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
      </div>
    );
  }

  // ── Success ──────────────────────────────────────────────────────────────────
  if (done) {
    return (
      <>
        <Navbar />
        <Sidebar />
        <div className="pl-14">
        <main className="mx-auto max-w-2xl px-4 py-16 text-center">
          <div className="mb-4 flex justify-center"><span className="text-5xl">🎉</span></div>
          <h1 className="text-2xl font-bold text-gray-900 mb-2">Profil gespeichert</h1>
          <p className="text-gray-500 mb-6">
            Dein Kandidatenprofil ist gespeichert.
            {profile.completeness_score > 0 && (
              <> Vollständigkeit: <Badge variant="secondary">{profile.completeness_score}%</Badge></>
            )}
          </p>
          <div className="text-left mb-6 rounded-xl border border-gray-200 bg-white p-5">
            <ExportButtons />
          </div>
          <div className="text-left mb-6">
            <SkillGapWidget />
          </div>
          <div className="text-left mb-6">
            <AvailabilityWidget />
          </div>
          <Button onClick={() => { setStep(1); setDone(false); }}>Profil bearbeiten</Button>
        </main>
        </div>
      </>
    );
  }

  // ── Steps ────────────────────────────────────────────────────────────────────
  const titles = ["Basisdaten", "Kenntnisse", "Lebenslauf hochladen"];

  return (
    <>
      <Navbar />
      <Sidebar />
      <div className="pl-14">
      <main className="mx-auto max-w-2xl px-4 py-10">
        <h1 className="mb-6 text-2xl font-bold text-gray-900">Mein Profil</h1>
        <Steps current={step} />

        <Card>
          <CardHeader>
            <CardTitle>{titles[step - 1]}</CardTitle>
          </CardHeader>
          <CardContent>
            {step === 1 && (
              <StepBasicInfo profile={profile} onSave={handleBasicInfo} />
            )}
            {step === 2 && (
              <StepSkills profile={profile} onSave={handleSkills} />
            )}
            {step === 3 && (
              <div className="space-y-5">
                <StepCV profile={profile} token={token} onDone={(updatedProfile) => handleCVDone(updatedProfile)} />
                <Button variant="outline" onClick={() => setDone(true)}>
                  Ohne CV-Upload abschließen
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        {step > 1 && step < 4 && (
          <button
            onClick={() => setStep(step - 1)}
            className="mt-4 text-sm text-gray-400 hover:text-gray-600 transition-colors"
          >
            ← Zurück
          </button>
        )}
        <section aria-label="Export und Freigabe" className="mt-8 rounded-xl border border-gray-200 bg-white p-5">
          <ExportButtons />
        </section>
      </main>
      </div>
    </>
  );
}
