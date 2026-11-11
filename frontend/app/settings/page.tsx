"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/auth";
import { authApi, jobAlertsApi, ApiError } from "@/lib/api";
import type { UserRead, JobAlertRead } from "@/lib/api";
import { Navbar } from "@/components/layout/Navbar";
import { Sidebar } from "@/components/layout/Sidebar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function SettingsPage() {
  const router = useRouter();
  const [user, setUser] = useState<UserRead | null>(null);
  const [consent, setConsent] = useState<{ ai_opt_in: boolean; terms_accepted: boolean } | null>(null);
  const [loading, setLoading] = useState(true);

  // Profile form
  const [fullName, setFullName] = useState("");
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileMsg, setProfileMsg] = useState<string | null>(null);

  // Password form
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [savingPassword, setSavingPassword] = useState(false);
  const [passwordMsg, setPasswordMsg] = useState<string | null>(null);

  // Consent
  const [aiOptIn, setAiOptIn] = useState(false);
  const [savingConsent, setSavingConsent] = useState(false);
  const [consentMsg, setConsentMsg] = useState<string | null>(null);

  // Job alerts
  const [alerts, setAlerts] = useState<JobAlertRead[]>([]);
  const [alertKeywords, setAlertKeywords] = useState("");
  const [alertLocation, setAlertLocation] = useState("");
  const [alertRemoteOnly, setAlertRemoteOnly] = useState(false);
  const [alertCategory, setAlertCategory] = useState("");
  const [alertMinScore, setAlertMinScore] = useState(60);
  const [savingAlert, setSavingAlert] = useState(false);
  const [alertMsg, setAlertMsg] = useState<string | null>(null);

  useEffect(() => {
    const token = auth.getAccess();
    if (!token) { router.replace("/login"); return; }

    Promise.allSettled([
      authApi.me(token),
      authApi.getConsent(token),
      jobAlertsApi.list(token),
    ]).then(([userRes, consentRes, alertsRes]) => {
      if (userRes.status === "fulfilled") {
        setUser(userRes.value);
        setFullName(userRes.value.full_name ?? "");
      } else {
        router.replace("/login");
        return;
      }
      if (consentRes.status === "fulfilled" && consentRes.value) {
        setConsent(consentRes.value);
        setAiOptIn(consentRes.value.ai_opt_in);
      }
      if (alertsRes.status === "fulfilled") setAlerts(alertsRes.value);
    }).finally(() => setLoading(false));
  }, [router]);

  async function handleSaveProfile(e: React.FormEvent) {
    e.preventDefault();
    const token = auth.getAccess();
    if (!token) return;
    setSavingProfile(true);
    setProfileMsg(null);
    try {
      const updated = await authApi.updateMe(token, { full_name: fullName.trim() || undefined });
      setUser(updated);
      setProfileMsg("Änderungen gespeichert.");
    } catch (err) {
      setProfileMsg(err instanceof ApiError ? err.detail : "Fehler beim Speichern.");
    } finally {
      setSavingProfile(false);
    }
  }

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault();
    if (newPassword !== confirmPassword) {
      setPasswordMsg("Passwörter stimmen nicht überein.");
      return;
    }
    const token = auth.getAccess();
    if (!token) return;
    setSavingPassword(true);
    setPasswordMsg(null);
    try {
      await authApi.updateMe(token, { password: newPassword });
      setNewPassword("");
      setConfirmPassword("");
      setPasswordMsg("Passwort erfolgreich geändert.");
    } catch (err) {
      setPasswordMsg(err instanceof ApiError ? err.detail : "Fehler beim Ändern.");
    } finally {
      setSavingPassword(false);
    }
  }

  async function handleConsentSave() {
    const token = auth.getAccess();
    if (!token) return;
    setSavingConsent(true);
    setConsentMsg(null);
    try {
      await authApi.updateConsent(token, {
        ai_opt_in: aiOptIn,
        terms_accepted: consent?.terms_accepted ?? true,
      });
      setConsentMsg("Einwilligung aktualisiert.");
    } catch (err) {
      setConsentMsg(err instanceof ApiError ? err.detail : "Fehler.");
    } finally {
      setSavingConsent(false);
    }
  }

  async function handleCreateAlert(e: React.FormEvent) {
    e.preventDefault();
    const token = auth.getAccess();
    if (!token) return;
    setSavingAlert(true);
    setAlertMsg(null);
    try {
      const alert = await jobAlertsApi.create(token, {
        keywords: alertKeywords.trim() || null,
        location: alertLocation.trim() || null,
        remote_only: alertRemoteOnly,
        category: alertCategory || null,
        min_score: alertMinScore,
      });
      setAlerts((prev) => [alert, ...prev]);
      setAlertKeywords("");
      setAlertLocation("");
      setAlertRemoteOnly(false);
      setAlertCategory("");
      setAlertMinScore(60);
      setAlertMsg("Job-Alarm erstellt!");
    } catch (err) {
      setAlertMsg(err instanceof ApiError ? err.detail : "Fehler beim Erstellen.");
    } finally {
      setSavingAlert(false);
    }
  }

  async function handleDeleteAlert(alertId: string) {
    const token = auth.getAccess();
    if (!token) return;
    try {
      await jobAlertsApi.delete(token, alertId);
      setAlerts((prev) => prev.filter((a) => a.id !== alertId));
    } catch { /* ignore */ }
  }

  if (loading) {
    return (
      <>
        <Navbar />
        <Sidebar />
        <div className="flex min-h-[60vh] items-center justify-center">
          <div className="h-6 w-6 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      </>
    );
  }

  return (
    <>
      <Navbar />
      <Sidebar />
      <div className="pl-14">
      <main className="mx-auto max-w-2xl px-4 py-8 space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Konto-Einstellungen</h1>
          {user && <p className="text-sm text-gray-500 mt-0.5">{user.email}</p>}
        </div>

        {/* Profile */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Profil</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleSaveProfile} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="full_name">Anzeigename</Label>
                <Input
                  id="full_name"
                  value={fullName}
                  onChange={(e) => setFullName(e.target.value)}
                  placeholder="Max Mustermann"
                />
              </div>
              <div className="space-y-1.5">
                <Label>E-Mail</Label>
                <Input value={user?.email ?? ""} disabled className="bg-gray-50 text-gray-500" />
                <p className="text-xs text-gray-400">E-Mail-Änderung ist derzeit nicht möglich.</p>
              </div>
              {profileMsg && (
                <p className={`text-sm ${profileMsg.includes("Fehler") ? "text-red-600" : "text-green-600"}`}>
                  {profileMsg}
                </p>
              )}
              <Button type="submit" disabled={savingProfile}>
                {savingProfile ? "Wird gespeichert…" : "Speichern"}
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* Password */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Passwort ändern</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleChangePassword} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="new_password">Neues Passwort</Label>
                <Input
                  id="new_password"
                  type="password"
                  minLength={8}
                  required
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="Mindestens 8 Zeichen"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="confirm_password">Passwort bestätigen</Label>
                <Input
                  id="confirm_password"
                  type="password"
                  minLength={8}
                  required
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="Passwort wiederholen"
                />
              </div>
              {passwordMsg && (
                <p className={`text-sm ${passwordMsg.includes("Fehler") || passwordMsg.includes("stimmen") ? "text-red-600" : "text-green-600"}`}>
                  {passwordMsg}
                </p>
              )}
              <Button type="submit" disabled={savingPassword}>
                {savingPassword ? "Wird geändert…" : "Passwort ändern"}
              </Button>
            </form>
          </CardContent>
        </Card>

        {/* Privacy / Consent */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Datenschutz & Einwilligungen</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <label className="flex items-start gap-3 cursor-pointer">
              <input
                type="checkbox"
                checked={aiOptIn}
                onChange={(e) => setAiOptIn(e.target.checked)}
                className="mt-0.5 rounded border-gray-300"
              />
              <span className="text-sm text-gray-700 leading-relaxed">
                KI-gestützte Analyse meines Profils (CV-Parser, Job-Matching, Anschreiben-Generator)
                <span className="block text-xs text-gray-400 mt-0.5">
                  Diese Einwilligung ist freiwillig und jederzeit widerrufbar.
                </span>
              </span>
            </label>
            {consentMsg && (
              <p className={`text-sm ${consentMsg.includes("Fehler") ? "text-red-600" : "text-green-600"}`}>
                {consentMsg}
              </p>
            )}
            <Button variant="outline" onClick={handleConsentSave} disabled={savingConsent}>
              {savingConsent ? "Wird gespeichert…" : "Einwilligung speichern"}
            </Button>
          </CardContent>
        </Card>

        {/* Job Alerts */}
        {user?.role !== "recruiter" && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Job-Alarme</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <p className="text-sm text-gray-500">
                Erhalte E-Mail-Benachrichtigungen wenn neue passende Jobs eingestellt werden.
              </p>

              {/* Existing alerts */}
              {alerts.length > 0 && (
                <div className="space-y-2">
                  {alerts.map((a) => (
                    <div key={a.id} className="flex items-center justify-between rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
                      <div className="text-sm text-gray-700 space-x-2">
                        {a.keywords && <span>🔍 {a.keywords}</span>}
                        {a.location && <span>📍 {a.location}</span>}
                        {a.remote_only && <span>🌐 Remote</span>}
                        {a.category && <span>📂 {a.category}</span>}
                        <span className="text-xs text-gray-400">≥{a.min_score}% Match</span>
                      </div>
                      <button
                        onClick={() => handleDeleteAlert(a.id)}
                        className="ml-2 text-xs text-red-500 hover:text-red-700"
                      >
                        Löschen
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {/* New alert form */}
              <form onSubmit={handleCreateAlert} className="space-y-3 pt-2 border-t border-gray-100">
                <p className="text-xs font-medium text-gray-500 uppercase tracking-wide">Neuer Alarm</p>
                <div className="grid grid-cols-2 gap-3">
                  <div className="space-y-1.5">
                    <Label htmlFor="alert_keywords" className="text-xs">Suchbegriff</Label>
                    <Input
                      id="alert_keywords"
                      value={alertKeywords}
                      onChange={(e) => setAlertKeywords(e.target.value)}
                      placeholder="z.B. React Developer"
                      className="text-sm"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="alert_location" className="text-xs">Ort</Label>
                    <Input
                      id="alert_location"
                      value={alertLocation}
                      onChange={(e) => setAlertLocation(e.target.value)}
                      placeholder="z.B. Berlin"
                      className="text-sm"
                    />
                  </div>
                </div>
                <div className="flex items-center gap-4 flex-wrap">
                  <label className="flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={alertRemoteOnly}
                      onChange={(e) => setAlertRemoteOnly(e.target.checked)}
                      className="rounded"
                    />
                    Nur Remote
                  </label>
                  <div className="flex items-center gap-2 text-sm text-gray-700">
                    <span>Min. Match:</span>
                    <select
                      value={alertMinScore}
                      onChange={(e) => setAlertMinScore(Number(e.target.value))}
                      className="rounded border border-gray-200 px-2 py-1 text-xs"
                    >
                      <option value={50}>50%</option>
                      <option value={60}>60%</option>
                      <option value={70}>70%</option>
                      <option value={80}>80%</option>
                    </select>
                  </div>
                </div>
                {alertMsg && (
                  <p className={`text-sm ${alertMsg.includes("Fehler") ? "text-red-600" : "text-green-600"}`}>
                    {alertMsg}
                  </p>
                )}
                <Button type="submit" size="sm" disabled={savingAlert}>
                  {savingAlert ? "Wird erstellt…" : "Alarm erstellen"}
                </Button>
              </form>
            </CardContent>
          </Card>
        )}

        {/* Account info */}
        {user && (
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Konto-Informationen</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm text-gray-600">
              <p><span className="font-medium text-gray-700">Rolle:</span> {user.role === "recruiter" ? "Recruiter" : "Kandidat"}</p>
              <p><span className="font-medium text-gray-700">Mitglied seit:</span> {new Date(user.created_at).toLocaleDateString("de-DE", { day: "2-digit", month: "long", year: "numeric" })}</p>
              <p><span className="font-medium text-gray-700">Konto-ID:</span> <span className="font-mono text-xs text-gray-400">{user.id}</span></p>
            </CardContent>
          </Card>
        )}
      </main>
      </div>
    </>
  );
}
