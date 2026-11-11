"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Search, MapPin, ArrowLeft, Bookmark, Users, ChevronRight } from "lucide-react";
import { auth } from "@/lib/auth";
import { applicationLabels, errorMessage, workspaceApi, type Person, type PersonDetail } from "@/lib/workspace";

export default function PeoplePage() { return <Suspense fallback={<p role="status" className="p-8">Menschen werden geladen …</p>}><PeopleWorkspace /></Suspense>; }

function PeopleWorkspace() {
  const params = useSearchParams();
  const router = useRouter();
  const q = params.get("q") ?? "";
  const role = params.get("role") ?? "all";
  const selected = params.get("person");
  const offset = Math.max(0, Number(params.get("offset")) || 0);
  const [input, setInput] = useState(q);
  const [people, setPeople] = useState<Person[]>([]);
  const [total, setTotal] = useState(0);
  const [detail, setDetail] = useState<PersonDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");
  const [detailError, setDetailError] = useState("");
  const [saved, setSaved] = useState<{ name: string; query: string }[]>([]);
  const [notice, setNotice] = useState("");
  const storageKey = () => { const user = auth.getUser(); return `hireos:people-views:${user?.tenant_id}:${user?.sub}`; };
  useEffect(() => {
    try { const value: unknown = JSON.parse(localStorage.getItem(storageKey()) ?? "[]"); if (Array.isArray(value)) setSaved(value.filter(v => typeof v?.name === "string" && typeof v?.query === "string").slice(0, 8)); } catch { /* A corrupt preference must not block work. */ }
  }, []);
  useEffect(() => { setInput(q); }, [q]);
  function navigate(changes: Record<string, string | null>) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) { if (value) next.set(key, value); else next.delete(key); }
    router.push(`/dashboard/people?${next}`, { scroll: false });
  }
  useEffect(() => {
    const controller = new AbortController();
    const token = auth.getAccess(); if (!token) return;
    setLoading(true); setError("");
    const query = new URLSearchParams({ q, role, offset: String(offset) });
    workspaceApi.people(token, query, controller.signal).then(data => { setPeople(data.people); setTotal(data.total); }).catch(e => { if (!controller.signal.aborted) setError(errorMessage(e)); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [q, role, offset]);
  useEffect(() => {
    const controller = new AbortController();
    setDetail(null); setDetailError("");
    if (!selected) { setDetailLoading(false); return; }
    const token = auth.getAccess(); if (!token) return;
    setDetailLoading(true);
    workspaceApi.person(token, selected, controller.signal).then(setDetail).catch(e => { if (!controller.signal.aborted) setDetailError(errorMessage(e)); }).finally(() => { if (!controller.signal.aborted) setDetailLoading(false); });
    return () => controller.abort();
  }, [selected]);
  function saveView() {
    const query = new URLSearchParams({ q, role }).toString();
    const name = q || (role === "worker" ? "Mitarbeitende" : role === "candidate" ? "Bewerbende" : "Alle Menschen");
    const next = [{ name, query }, ...saved.filter(v => v.query !== query)].slice(0, 8);
    try { localStorage.setItem(storageKey(), JSON.stringify(next)); setSaved(next); setNotice("Ansicht in diesem Browser gespeichert."); } catch { setNotice("Die Ansicht konnte in diesem Browser nicht gespeichert werden."); }
  }
  return <div className="mx-auto max-w-7xl space-y-5 px-4 py-7 sm:px-8">
    <header><p className="mb-2 text-sm font-medium text-blue-700">Talente & Mitarbeitende</p><h1 className="text-3xl font-semibold tracking-tight">Menschen</h1><p className="mt-2 text-sm text-slate-600">Profile und gemeinsame Vorgänge. Suche nach Namen, Fähigkeiten oder Ort.</p></header>
    <form onSubmit={e => { e.preventDefault(); navigate({ q: input.trim(), offset: null }); }} className="flex flex-wrap gap-3">
      <div className="relative min-w-0 flex-1 basis-64"><Search size={18} className="absolute left-3 top-3.5 text-slate-400" aria-hidden="true" /><input aria-label="Menschen suchen" value={input} onChange={e => setInput(e.target.value)} placeholder="Name, Fähigkeit oder Ort …" maxLength={150} className="min-h-11 w-full rounded-xl border border-slate-200 bg-white pl-10 pr-3 text-sm" /></div>
      <select aria-label="Personengruppe" value={role} onChange={e => navigate({ role: e.target.value, offset: null })} className="min-h-11 rounded-xl border border-slate-200 bg-white px-3 text-sm"><option value="all">Alle Menschen</option><option value="candidate">Bewerbende</option><option value="worker">Mitarbeitende</option></select>
      <button className="min-h-11 rounded-xl bg-blue-600 px-5 text-sm font-semibold text-white">Suchen</button><button type="button" onClick={saveView} className="flex min-h-11 items-center gap-2 rounded-xl border bg-white px-3 text-sm"><Bookmark size={16} aria-hidden="true" />Ansicht speichern</button>
    </form>
    {notice && <p role="status" className="text-sm text-blue-700">{notice}</p>}
    {saved.length > 0 && <div className="flex flex-wrap gap-2" aria-label="Gespeicherte Ansichten">{saved.map(view => <Link key={view.query} href={`/dashboard/people?${view.query}`} className="inline-flex min-h-11 items-center rounded-xl bg-slate-100 px-3 text-sm text-slate-700">{view.name}</Link>)}</div>}
    <div className="grid min-h-[30rem] overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm lg:grid-cols-[minmax(17rem,0.85fr)_minmax(0,1.5fr)]">
      <section aria-label="Personenliste" className={`${selected ? "hidden lg:block" : ""} border-slate-200 lg:border-r`}>
        <div className="border-b border-slate-100 p-4 text-sm text-slate-600" aria-live="polite">{loading ? "Suche läuft …" : `${total} Personen`}</div>
        {error ? <p role="alert" className="p-5 text-red-700">{error}</p> : loading ? <p role="status" className="p-8 text-sm text-slate-500">Profile werden geladen …</p> : people.length === 0 ? <div className="p-8"><Users size={28} className="mb-3 text-blue-600" aria-hidden="true" /><h2 className="font-semibold">Noch keine passenden Personen</h2><p className="mt-2 text-sm text-slate-600">Bewerbende werden sichtbar, sobald sie sich auf eine Stelle deines Arbeitsbereichs bewerben. Mitarbeitende findest du nach ihrer Zuordnung.</p></div> : <ul className="divide-y divide-slate-100">{people.map(person => <li key={person.id}><button onClick={() => navigate({ person: person.id })} aria-pressed={selected === person.id} className={`flex w-full items-center gap-3 p-4 text-left hover:bg-slate-50 ${selected === person.id ? "bg-blue-50/70" : ""}`}><span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-blue-100 text-sm font-semibold text-blue-800">{(person.full_name ?? person.email).slice(0, 2).toUpperCase()}</span><span className="min-w-0 flex-1"><span className="block truncate text-sm font-semibold">{person.full_name ?? person.email}</span><span className="block truncate text-xs text-slate-600">{person.headline ?? (person.role === "worker" ? "Mitarbeitend" : "Bewerbend")}</span>{person.location && <span className="block truncate text-xs text-slate-500">{person.location}</span>}</span><ChevronRight size={16} className="shrink-0 text-slate-400" aria-hidden="true" /></button></li>)}</ul>}
        <div className="flex justify-between gap-2 border-t p-3"><button disabled={!offset || loading} onClick={() => navigate({ offset: String(Math.max(0, offset - 40)) })} className="min-h-11 rounded-lg px-3 text-sm disabled:opacity-40">Zurück</button><button disabled={offset + 40 >= total || loading} onClick={() => navigate({ offset: String(offset + 40) })} className="min-h-11 rounded-lg px-3 text-sm disabled:opacity-40">Weitere Personen</button></div>
      </section>
      <section aria-label="Personenakte" className={`${!selected ? "hidden lg:block" : ""} min-w-0 p-5 sm:p-7`}>
        {selected && <button onClick={() => navigate({ person: null })} className="mb-5 inline-flex min-h-11 items-center gap-2 rounded-lg px-2 text-sm text-slate-600"><ArrowLeft size={16} />Zur Personenliste</button>}
        {detailLoading ? <p role="status">Personenakte wird geladen …</p> : detailError ? <p role="alert" className="text-red-700">{detailError}</p> : !detail ? <div className="flex min-h-80 flex-col items-center justify-center text-center"><Users size={36} className="mb-4 text-blue-500" aria-hidden="true" /><h2 className="font-semibold">Eine Person, alle nächsten Schritte</h2><p className="mt-2 max-w-sm text-sm text-slate-600">Wähle links ein Profil. Deine Suche und Position in der Liste bleiben erhalten.</p></div> : <div className="space-y-6">
          <header><span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-medium text-blue-700">{detail.role === "worker" ? "Mitarbeitend" : "Bewerbend"}</span><h2 className="mt-3 break-words text-2xl font-semibold">{detail.full_name ?? detail.email}</h2>{detail.headline && <p className="mt-1 text-slate-600">{detail.headline}</p>}<p className="mt-2 break-all text-sm text-slate-600">{detail.email}</p>{detail.location && <p className="mt-2 flex items-center gap-1 text-sm text-slate-500"><MapPin size={14} />{detail.location}</p>}</header>
          {detail.summary && <section><h3 className="mb-2 text-sm font-semibold">Überblick</h3><p className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-600">{detail.summary}</p></section>}
          <Link href={`/dashboard/communication?person=${detail.id}`} className="inline-flex min-h-11 items-center rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white">Nachricht vorbereiten</Link><section><h3 className="mb-3 text-sm font-semibold">Fähigkeiten</h3>{detail.skills.length ? <div className="flex flex-wrap gap-2">{detail.skills.map((skill, index) => <span key={`${skill.name}-${index}`} title={skill.source ? `Quelle: ${skill.source}` : "Aus dem Profil"} className="rounded-lg bg-slate-100 px-3 py-2 text-xs text-slate-700">{skill.name}</span>)}</div> : <p className="text-sm text-slate-500">Noch keine Fähigkeiten im Profil hinterlegt.</p>}</section>
          {detail.experience.length > 0 && <section><h3 className="mb-3 text-sm font-semibold">Berufserfahrung</h3><ul className="space-y-4">{detail.experience.map((item, i) => <li key={i} className="border-l-2 border-blue-100 pl-4"><p className="text-sm font-medium">{item.title}</p><p className="text-xs text-slate-500">{item.company}</p>{item.description && <p className="mt-1 whitespace-pre-wrap text-sm text-slate-600">{item.description}</p>}</li>)}</ul></section>}
          <section><h3 className="mb-3 text-sm font-semibold">Bewerbungen in diesem Arbeitsbereich</h3>{detail.applications.length ? <ul className="space-y-2">{detail.applications.map(application => <li key={application.id}><Link href={`/dashboard/applications?application=${application.id}`} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border p-4 hover:border-blue-300"><span className="text-sm font-medium">{application.position}</span><span className="rounded-full bg-slate-100 px-2 py-1 text-xs">{applicationLabels[application.status] ?? application.status}</span></Link><Link href={`/dashboard/scheduling?application=${application.id}`} className="mt-1 inline-flex min-h-11 items-center px-3 text-sm text-blue-700">Terminauswahl anbieten</Link><Link href={`/dashboard/offers?application=${application.id}`} className="inline-flex min-h-11 items-center text-sm text-blue-700">Angebot vorbereiten</Link></li>)}</ul> : <p className="text-sm text-slate-500">Keine gemeinsamen Bewerbungen vorhanden.</p>}</section>
          {detail.role === "worker" && <div className="flex flex-wrap gap-2"><Link className="inline-flex min-h-11 items-center rounded-xl border px-3 text-sm" href="/dashboard/zeitarbeit/workers">Mitarbeitendenverwaltung</Link><Link className="inline-flex min-h-11 items-center rounded-xl border px-3 text-sm" href="/dashboard/zeitarbeit/tasks">Aufgaben verwalten</Link></div>}
        </div>}
      </section>
    </div>
  </div>;
}
