"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { User, Phone, MapPin, Heart, CreditCard, Lock, CheckCircle2, AlertCircle } from "lucide-react";
import { auth } from "@/lib/auth";
import { workerProfileApi, WorkerProfileRead, WorkerProfileUpdate } from "@/lib/api";

// ── Section ───────────────────────────────────────────────────────────────────

function Section({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-5">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-gray-900 mb-4">
        <span className="text-gray-400">{icon}</span>
        {title}
      </h2>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-gray-600 mb-1">{label}</label>
      {children}
    </div>
  );
}

function Input({ value, onChange, placeholder, type = "text", disabled = false }: {
  value: string; onChange: (v: string) => void; placeholder?: string; type?: string; disabled?: boolean;
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      disabled={disabled}
      className="w-full border border-gray-300 rounded-xl px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:bg-gray-50 disabled:text-gray-400"
    />
  );
}

// ── Toast ─────────────────────────────────────────────────────────────────────

function Toast({ msg, ok }: { msg: string; ok: boolean }) {
  return (
    <div className={`fixed bottom-6 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 px-4 py-2.5 rounded-xl shadow-lg text-sm font-medium text-white ${ok ? "bg-green-600" : "bg-red-600"}`}>
      {ok ? <CheckCircle2 className="w-4 h-4" /> : <AlertCircle className="w-4 h-4" />}
      {msg}
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const EMPLOYMENT_LABELS: Record<string, string> = {
  fulltime: "Vollzeit", parttime: "Teilzeit", minijob: "Minijob", temp: "Zeitarbeit",
};

export default function WorkerProfilePage() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [profile, setProfile] = useState<WorkerProfileRead | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ msg: string; ok: boolean } | null>(null);

  // Form state
  const [form, setForm] = useState<WorkerProfileUpdate>({});
  const [pwForm, setPwForm] = useState({ current: "", next: "", confirm: "" });
  const [pwError, setPwError] = useState("");

  useEffect(() => {
    const t = auth.getAccess();
    if (!t) { router.replace("/login"); return; }
    setToken(t);
  }, [router]);

  const load = useCallback(async (t: string) => {
    setLoading(true);
    try {
      const p = await workerProfileApi.get(t);
      setProfile(p);
      setForm({
        full_name: p.full_name ?? "",
        phone: p.phone ?? "",
        address_street: p.address_street ?? "",
        address_city: p.address_city ?? "",
        address_zip: p.address_zip ?? "",
        address_country: p.address_country ?? "DE",
        date_of_birth: p.date_of_birth ?? "",
        emergency_contact_name: p.emergency_contact_name ?? "",
        emergency_contact_phone: p.emergency_contact_phone ?? "",
        iban: p.iban ?? "",
      });
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { if (token) load(token); }, [token, load]);

  function showToast(msg: string, ok: boolean) {
    setToast({ msg, ok });
    setTimeout(() => setToast(null), 3000);
  }

  async function handleSave() {
    if (!token) return;
    setSaving(true);
    try {
      // Only send non-empty changed fields
      const body: WorkerProfileUpdate = {};
      for (const [k, v] of Object.entries(form)) {
        if (v !== "") (body as Record<string, string>)[k] = v as string;
      }
      const updated = await workerProfileApi.update(token, body);
      setProfile(updated);
      showToast("Profil gespeichert", true);
    } catch {
      showToast("Fehler beim Speichern", false);
    } finally {
      setSaving(false);
    }
  }

  async function handleChangePassword() {
    if (!token) return;
    setPwError("");
    if (pwForm.next !== pwForm.confirm) { setPwError("Passwörter stimmen nicht überein"); return; }
    if (pwForm.next.length < 8) { setPwError("Mindestens 8 Zeichen"); return; }
    setSaving(true);
    try {
      await workerProfileApi.changePassword(token, pwForm.current, pwForm.next);
      setPwForm({ current: "", next: "", confirm: "" });
      showToast("Passwort geändert", true);
    } catch {
      setPwError("Aktuelles Passwort falsch oder Fehler");
    } finally {
      setSaving(false);
    }
  }

  if (loading) return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <p className="text-gray-400 text-sm">Lade...</p>
    </div>
  );

  return (
    <div className="min-h-screen bg-gray-50 p-4 md:p-6">
      <div className="max-w-2xl mx-auto space-y-4">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Mein Profil</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              {profile?.email}
              {profile && (
                <span className="ml-2 text-xs text-gray-400">
                  · {EMPLOYMENT_LABELS[profile.employment_type] ?? profile.employment_type}
                </span>
              )}
            </p>
          </div>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-xl hover:bg-blue-700 disabled:opacity-40"
          >
            {saving ? "Speichern..." : "Speichern"}
          </button>
        </div>

        {/* Persönliche Daten */}
        <Section title="Persönliche Daten" icon={<User className="w-4 h-4" />}>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Name">
              <Input value={form.full_name ?? ""} onChange={(v) => setForm(f => ({ ...f, full_name: v }))} placeholder="Max Mustermann" />
            </Field>
            <Field label="Geburtsdatum">
              <Input type="date" value={form.date_of_birth ?? ""} onChange={(v) => setForm(f => ({ ...f, date_of_birth: v }))} />
            </Field>
            <Field label="E-Mail">
              <Input value={profile?.email ?? ""} onChange={() => {}} disabled />
            </Field>
          </div>
        </Section>

        {/* Kontakt */}
        <Section title="Kontakt" icon={<Phone className="w-4 h-4" />}>
          <div className="grid grid-cols-1 gap-3">
            <Field label="Telefonnummer">
              <Input value={form.phone ?? ""} onChange={(v) => setForm(f => ({ ...f, phone: v }))} placeholder="+49 170 1234567" />
            </Field>
          </div>
        </Section>

        {/* Adresse */}
        <Section title="Adresse" icon={<MapPin className="w-4 h-4" />}>
          <div className="grid grid-cols-1 gap-3">
            <Field label="Straße und Hausnummer">
              <Input value={form.address_street ?? ""} onChange={(v) => setForm(f => ({ ...f, address_street: v }))} placeholder="Musterstraße 1" />
            </Field>
            <div className="grid grid-cols-3 gap-3">
              <Field label="PLZ">
                <Input value={form.address_zip ?? ""} onChange={(v) => setForm(f => ({ ...f, address_zip: v }))} placeholder="12345" />
              </Field>
              <div className="col-span-2">
                <Field label="Stadt">
                  <Input value={form.address_city ?? ""} onChange={(v) => setForm(f => ({ ...f, address_city: v }))} placeholder="Berlin" />
                </Field>
              </div>
            </div>
            <Field label="Land">
              <Input value={form.address_country ?? "DE"} onChange={(v) => setForm(f => ({ ...f, address_country: v }))} placeholder="DE" />
            </Field>
          </div>
        </Section>

        {/* Notfallkontakt */}
        <Section title="Notfallkontakt" icon={<Heart className="w-4 h-4" />}>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <Field label="Name">
              <Input value={form.emergency_contact_name ?? ""} onChange={(v) => setForm(f => ({ ...f, emergency_contact_name: v }))} placeholder="Anna Mustermann" />
            </Field>
            <Field label="Telefon">
              <Input value={form.emergency_contact_phone ?? ""} onChange={(v) => setForm(f => ({ ...f, emergency_contact_phone: v }))} placeholder="+49 170 9876543" />
            </Field>
          </div>
        </Section>

        {/* Bankverbindung */}
        <Section title="Bankverbindung" icon={<CreditCard className="w-4 h-4" />}>
          <Field label="IBAN">
            <Input
              value={form.iban ?? ""}
              onChange={(v) => setForm(f => ({ ...f, iban: v.replace(/\s/g, "").toUpperCase() }))}
              placeholder="DE89 3704 0044 0532 0130 00"
            />
          </Field>
          <p className="text-xs text-gray-400 mt-1.5">Wird für die Lohnüberweisung genutzt.</p>
        </Section>

        {/* Passwort ändern */}
        <Section title="Passwort ändern" icon={<Lock className="w-4 h-4" />}>
          <div className="grid grid-cols-1 gap-3">
            <Field label="Aktuelles Passwort">
              <Input type="password" value={pwForm.current} onChange={(v) => setPwForm(f => ({ ...f, current: v }))} placeholder="••••••••" />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Neues Passwort">
                <Input type="password" value={pwForm.next} onChange={(v) => setPwForm(f => ({ ...f, next: v }))} placeholder="min. 8 Zeichen" />
              </Field>
              <Field label="Wiederholen">
                <Input type="password" value={pwForm.confirm} onChange={(v) => setPwForm(f => ({ ...f, confirm: v }))} placeholder="••••••••" />
              </Field>
            </div>
            {pwError && <p className="text-xs text-red-600">{pwError}</p>}
            <button
              onClick={handleChangePassword}
              disabled={saving || !pwForm.current || !pwForm.next || !pwForm.confirm}
              className="w-full py-2.5 text-sm text-white bg-gray-800 rounded-xl hover:bg-gray-900 disabled:opacity-40"
            >
              Passwort ändern
            </button>
          </div>
        </Section>
      </div>

      {toast && <Toast msg={toast.msg} ok={toast.ok} />}
    </div>
  );
}
