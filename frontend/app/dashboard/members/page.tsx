"use client";

import { useCallback, useEffect, useState } from "react";
import { auth } from "@/lib/auth";
import { authApi, type UserRead } from "@/lib/api";
import { errorMessage, workspaceApi, type Invitation } from "@/lib/workspace";

export default function MembersPage() {
  const [members, setMembers] = useState<UserRead[]>([]);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [owner, setOwner] = useState<string | null>(null);
  const [me, setMe] = useState<UserRead | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("recruiter");
  const [link, setLink] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    const token = auth.getAccess(); if (!token) return;
    try { const [data, user] = await Promise.all([workspaceApi.members(token), authApi.me(token)]); setMembers(data.members); setInvitations(data.invitations); setOwner(data.owner_id); setMe(user); }
    catch (e) { setError(errorMessage(e)); } finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  async function invite(e: React.FormEvent) {
    e.preventDefault(); const token = auth.getAccess(); if (!token) return;
    setBusy(true); setError(""); setNotice(""); setLink("");
    try { const invitation = await workspaceApi.invite(token, email, role); setLink(`${window.location.origin}/invite#${invitation.token}`); setEmail(""); setNotice("Einladung erstellt. Der Link gilt sieben Tage und nur für die angegebene E-Mail-Adresse."); await load(); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function revoke(id: string) {
    const token = auth.getAccess(); if (!token) return;
    setBusy(true); setError("");
    try { await workspaceApi.revoke(token, id); setLink(""); setNotice("Einladung widerrufen."); await load(); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function changeRole(id: string, next: string) {
    const token = auth.getAccess(); if (!token) return;
    setBusy(true); setError("");
    try { await workspaceApi.role(token, id, next); setNotice("Rolle geändert. Das Mitglied muss sich erneut anmelden."); await load(); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  return <div className="mx-auto max-w-5xl space-y-6 px-4 py-8 sm:px-8"><header><h1 className="text-3xl font-semibold tracking-tight">Team & Zugänge</h1><p className="mt-2 text-sm text-slate-600">Lade dein Recruiting-Team ein und verwalte die Firmenrechte.</p></header>
    {error && <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</p>}{notice && <p role="status" className="rounded-xl bg-blue-50 p-4 text-sm text-blue-800">{notice}</p>}
    {loading ? <p role="status">Zugänge werden geladen …</p> : me?.role === "admin" && <>
      <form onSubmit={invite} className="space-y-4 rounded-2xl border bg-white p-5"><h2 className="font-semibold">Kollegin oder Kollegen einladen</h2><div className="flex flex-wrap items-end gap-3"><label className="min-w-0 flex-1 basis-60 text-sm">E-Mail-Adresse<input required type="email" value={email} onChange={e => setEmail(e.target.value)} className="mt-2 min-h-11 w-full rounded-xl border px-3" /></label><label className="text-sm">Rolle<select value={role} onChange={e => setRole(e.target.value)} className="mt-2 block min-h-11 rounded-xl border px-3"><option value="recruiter">Recruiting</option>{owner === me.id && <option value="admin">Firmenadministration</option>}</select></label><button disabled={busy || !me.company_id} className="min-h-11 rounded-xl bg-blue-600 px-5 text-sm font-semibold text-white disabled:opacity-50">Einladungslink erstellen</button></div><p className="text-xs leading-5 text-slate-500">Recruiting bearbeitet Personen und Vorgänge im Firmenarbeitsbereich. Die Firmenadministration verwaltet zusätzlich Zugänge und den Tarif. Mitarbeitendenzugänge werden in der Mitarbeitendenverwaltung angelegt.</p>{!me.company_id && <p className="text-sm text-amber-800">Diesem bestehenden Arbeitsbereich fehlt die Zuordnung zu einem Unternehmensprofil. Einladungen sind deshalb noch nicht verfügbar.</p>}
        {link && <div className="rounded-xl bg-slate-50 p-4"><label className="text-sm font-medium">Einladungslink<input readOnly value={link} onFocus={e => e.target.select()} className="mt-2 min-h-11 w-full rounded-lg border bg-white px-3 text-xs" /></label><button type="button" onClick={() => { void navigator.clipboard.writeText(link).then(() => setNotice("Link kopiert."), () => setNotice("Bitte den Link im Feld markieren und kopieren.")); }} className="mt-2 min-h-11 rounded-lg border bg-white px-3 text-sm">Link kopieren</button><p className="mt-2 text-xs text-slate-500">Teile diesen Link persönlich mit der eingeladenen Person.</p></div>}
      </form>
      <section className="overflow-hidden rounded-2xl border bg-white"><h2 className="border-b p-5 font-semibold">Mitglieder ({members.length})</h2><ul className="divide-y">{members.map(member => <li key={member.id} className="flex flex-wrap items-center justify-between gap-3 p-5"><div className="min-w-0"><p className="break-words text-sm font-semibold">{member.full_name ?? member.email}{member.id === owner && <span className="ml-2 rounded-full bg-blue-50 px-2 py-1 text-xs text-blue-700">Firmeninhaber</span>}</p><p className="mt-1 break-all text-xs text-slate-500">{member.email}{!member.is_active && " · Deaktiviert"}</p></div>{me.id === owner && member.id !== owner && ["admin", "recruiter"].includes(member.role) && member.is_active ? <select aria-label={`Rolle für ${member.email}`} value={member.role} disabled={busy} onChange={e => void changeRole(member.id, e.target.value)} className="min-h-11 rounded-xl border px-3 text-sm"><option value="recruiter">Recruiting</option><option value="admin">Firmenadministration</option></select> : <span className="text-sm text-slate-600">{member.role === "admin" ? "Firmenadministration" : member.role === "worker" ? "Mitarbeitend" : "Recruiting"}</span>}</li>)}</ul></section>
      <section className="overflow-hidden rounded-2xl border bg-white"><h2 className="border-b p-5 font-semibold">Einladungen</h2>{invitations.length === 0 ? <p className="p-5 text-sm text-slate-500">Noch keine Einladungen erstellt.</p> : <ul className="divide-y">{invitations.map(invitation => { const pending = !invitation.accepted_at && !invitation.revoked_at && new Date(invitation.expires_at).getTime() > Date.now(); return <li key={invitation.id} className="flex flex-wrap items-center justify-between gap-3 p-5"><div><p className="break-all text-sm font-medium">{invitation.email}</p><p className="mt-1 text-xs text-slate-500">{invitation.accepted_at ? "Angenommen" : invitation.revoked_at ? "Widerrufen" : pending ? `Gültig bis ${new Date(invitation.expires_at).toLocaleDateString("de-DE")}` : "Abgelaufen"}</p></div>{pending && <button disabled={busy} onClick={() => void revoke(invitation.id)} className="min-h-11 rounded-xl border px-4 text-sm text-red-700 disabled:opacity-50">Widerrufen</button>}</li>; })}</ul>}</section>
    </>}
  </div>;
}
