"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, CalendarDays, Check, RefreshCw, Sparkles, Users } from "lucide-react";
import { auth } from "@/lib/auth";
import { authApi, type WorkspaceRead } from "@/lib/api";
import { errorMessage, workspaceApi, type WorkspaceAction } from "@/lib/workspace";

const filters = [{ id: "all", label: "Alles" }, { id: "application", label: "Bewerbungen" }, { id: "interview", label: "Gespräche & Feedback" }, { id: "approval", label: "Freigaben" }, { id: "onboarding", label: "Onboarding" }];

export default function TodayPage() {
  const [actions, setActions] = useState<WorkspaceAction[]>([]);
  const [workspace, setWorkspace] = useState<WorkspaceRead | null>(null);
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("all");
  const load = useCallback(async () => {
    const token = auth.getAccess();
    if (!token) return;
    setLoading(true); setError("");
    try {
      const [today, company, user] = await Promise.all([workspaceApi.today(token), authApi.workspace(token), authApi.me(token)]);
      setActions(today.actions); setWorkspace(company); setName(user.full_name?.split(" ")[0] ?? "");
    } catch (e) { setError(errorMessage(e)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);
  const visible = actions.filter(a => filter === "all" || (filter === "interview" ? ["interview", "feedback"].includes(a.kind) : filter === "approval" ? ["time", "absence", "offer"].includes(a.kind) : a.kind === filter));
  return <div className="mx-auto max-w-6xl space-y-7 px-4 py-7 sm:px-8">
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div><p className="mb-2 text-sm font-medium text-blue-700">{workspace?.name ?? "Dein Arbeitsbereich"}</p><h1 className="text-3xl font-semibold tracking-tight text-slate-950">Heute</h1><p className="mt-2 text-slate-600">{name ? `Hallo ${name}. ` : ""}Hier findest du die nächsten Schritte für dein Team.</p></div>
      <Link href="/dashboard/jobs/new" className="inline-flex min-h-11 items-center rounded-xl bg-blue-600 px-5 text-sm font-semibold text-white hover:bg-blue-700">+ Neues Inserat</Link>
    </header>
    <div className="grid gap-3 sm:grid-cols-3">
      {[{ label: "Braucht Aufmerksamkeit", value: actions.filter(a => a.urgent).length, icon: Sparkles }, { label: "Gespräche in den nächsten 7 Tagen", value: actions.filter(a => a.kind === "interview").length, icon: CalendarDays }, { label: "Bewerbungen zur Sichtung", value: actions.filter(a => a.kind === "application").length, icon: Users }].map(({ label, value, icon: Icon }) => <div key={label} className="flex items-center gap-4 rounded-2xl border border-slate-200 bg-white p-5"><Icon size={22} className="text-blue-600" aria-hidden="true" /><div><p className="text-2xl font-semibold tabular-nums">{loading ? "–" : value}</p><p className="text-xs text-slate-600">{label}</p></div></div>)}
    </div>
    <section aria-label="Nächste Schritte" className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-5"><h2 className="font-semibold text-slate-900">Nächste Schritte</h2><button onClick={() => void load()} disabled={loading} aria-label="Übersicht aktualisieren" className="flex min-h-11 items-center gap-2 rounded-lg px-3 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50"><RefreshCw size={16} aria-hidden="true" /> Aktualisieren</button></div>
      <div className="flex gap-2 overflow-x-auto px-5 py-3" role="group" aria-label="Vorgänge filtern">{filters.map(item => <button key={item.id} onClick={() => setFilter(item.id)} aria-pressed={filter === item.id} className={`min-h-11 shrink-0 rounded-xl px-4 text-sm font-medium ${filter === item.id ? "bg-blue-50 text-blue-700" : "text-slate-600 hover:bg-slate-50"}`}>{item.label}</button>)}</div>
      {error ? <p role="alert" className="p-6 text-red-700">{error}</p> : loading ? <p role="status" className="p-10 text-center text-slate-500">Deine Vorgänge werden geladen …</p> : visible.length === 0 ? <div className="px-6 py-12 text-center"><Check className="mx-auto mb-3 text-emerald-600" size={30} aria-hidden="true" /><h3 className="font-semibold">{actions.length ? "Hier ist gerade alles erledigt" : "Raum für deinen nächsten Schritt"}</h3><p className="mx-auto mt-2 max-w-md text-sm text-slate-600">Neue Bewerbungen, Gespräche und offene Freigaben erscheinen hier automatisch.</p><Link href="/dashboard/jobs" className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-xl border px-4 text-sm font-medium">Stellen ansehen <ArrowRight size={16} /></Link></div> : <ul className="divide-y divide-slate-100">{visible.map(action => <li key={action.id} className="flex flex-wrap items-center justify-between gap-4 px-5 py-5 hover:bg-slate-50/60"><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h3 className="break-words text-sm font-semibold text-slate-900">{action.title}</h3>{action.urgent && <span className="rounded-full bg-amber-50 px-2 py-1 text-xs font-medium text-amber-800">Nachfassen</span>}</div><p className="mt-1 text-sm text-slate-600">{action.detail}</p>{action.due_at && <p className="mt-1 text-xs text-slate-500">{["interview", "feedback"].includes(action.kind) ? "Termin" : ["offer", "onboarding"].includes(action.kind) ? "Frist" : "Zuletzt aktualisiert"}: {new Date(action.due_at).toLocaleString("de-DE", { dateStyle: "medium", timeStyle: "short" })}</p>}</div><Link href={action.href} className="inline-flex min-h-11 items-center gap-2 rounded-xl border border-slate-200 bg-white px-4 text-sm font-medium text-blue-700 hover:border-blue-300">{action.action_label}<ArrowRight size={15} aria-hidden="true" /></Link></li>)}</ul>}
      <p className="border-t border-slate-100 px-5 py-3 text-xs text-slate-500">Jeweils bis zu 30 Bewerbungen, Gespräche, Angebote und Onboarding-Aufgaben, ergänzt um offene HR-Freigaben. Alle Vorgänge findest du in den jeweiligen Bereichen.</p>
    </section>
    <div className="flex flex-wrap gap-3 text-sm"><Link className="inline-flex min-h-11 items-center rounded-xl border bg-white px-4" href="/dashboard/people">Menschen entdecken</Link><Link className="inline-flex min-h-11 items-center rounded-xl border bg-white px-4" href="/dashboard/interviews">Gespräche planen</Link><Link className="inline-flex min-h-11 items-center rounded-xl border bg-white px-4" href="/dashboard/settings">Unternehmensprofil ergänzen</Link></div>
  </div>;
}
