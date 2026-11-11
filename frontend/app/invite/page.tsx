"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { authApi } from "@/lib/api";
import { errorMessage, workspaceApi } from "@/lib/workspace";

export default function InvitePage() {
  const [invitation, setInvitation] = useState("");
  const [loggedIn, setLoggedIn] = useState(false);
  const [account, setAccount] = useState("");
  const [register, setRegister] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    setInvitation(window.location.hash.slice(1));
    // The secret stays in the fragment (never in server request URLs or referrers).
    const token = auth.getAccess();
    if (token) authApi.me(token).then(user => { setLoggedIn(true); setAccount(user.email); }).catch(() => {});
  }, []);
  async function login(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError("");
    try { const tokens = register ? await authApi.register({ email, password, full_name: name }) : await authApi.login(email, password); auth.setTokens(tokens.access_token, tokens.refresh_token); setLoggedIn(true); setAccount(email); setPassword(""); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function accept() {
    const token = auth.getAccess(); if (!token) return;
    setBusy(true); setError("");
    try { const tokens = await workspaceApi.accept(token, invitation); auth.setTokens(tokens.access_token, tokens.refresh_token); window.history.replaceState(null, "", "/invite"); window.location.assign("/dashboard"); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  return <main className="flex min-h-dvh items-center justify-center bg-slate-50 p-4"><div className="w-full max-w-md space-y-5 rounded-3xl border bg-white p-7 shadow-sm"><Link href="/" className="font-semibold text-blue-700">FlintPlate</Link><h1 className="text-2xl font-semibold">Deinem Team beitreten</h1><p className="text-sm leading-6 text-slate-600">Melde dich mit der E-Mail-Adresse an, für die dein Team die Einladung erstellt hat.</p>{error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}{!invitation ? <p className="text-sm text-amber-800">Öffne bitte den vollständigen Einladungslink deines Teams.</p> : loggedIn ? <><p className="break-all text-sm">Angemeldet als <strong>{account}</strong></p><button disabled={busy} onClick={() => void accept()} className="min-h-11 w-full rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white disabled:opacity-50">Einladung annehmen</button><button onClick={() => { auth.clear(); setLoggedIn(false); }} className="min-h-11 w-full text-sm text-slate-600">Mit anderem Konto anmelden</button></> : <form onSubmit={login} className="space-y-4">{register && <label className="block text-sm">Name<input required value={name} onChange={e => setName(e.target.value)} autoComplete="name" className="mt-1 min-h-11 w-full rounded-xl border px-3" /></label>}<label className="block text-sm">E-Mail-Adresse<input required type="email" value={email} onChange={e => setEmail(e.target.value)} autoComplete="email" className="mt-1 min-h-11 w-full rounded-xl border px-3" /></label><label className="block text-sm">Passwort<input required type="password" minLength={8} value={password} onChange={e => setPassword(e.target.value)} autoComplete={register ? "new-password" : "current-password"} className="mt-1 min-h-11 w-full rounded-xl border px-3" /></label><button disabled={busy} className="min-h-11 w-full rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white disabled:opacity-50">{register ? "Konto erstellen" : "Anmelden"}</button><button type="button" onClick={() => setRegister(!register)} className="min-h-11 w-full text-sm text-slate-600">{register ? "Bereits ein Konto? Anmelden" : "Noch kein Konto? Registrieren"}</button></form>}</div></main>;
}
