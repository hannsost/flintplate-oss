"use client";
import { Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { authApi } from "@/lib/api";
import { errorMessage } from "@/lib/workspace";
import { journeysApi, type Journey, type JourneyTemplate, type PrivateOffer, type TeamOption } from "@/lib/journeys";
import { OnboardingCard } from "@/components/journeys/OnboardingCard";

export default function OnboardingPage() { return <Suspense fallback={<p role="status" className="p-8">Onboarding wird geöffnet …</p>}><Onboarding /></Suspense>; }
function Onboarding() {
  const offerId = useSearchParams().get("offer") ?? "";
  const [cases, setCases] = useState<Journey[]>([]);
  const [offers, setOffers] = useState<PrivateOffer[]>([]);
  const [team, setTeam] = useState<TeamOption[]>([]);
  const [templates, setTemplates] = useState<JourneyTemplate[]>([]);
  const [template, setTemplate] = useState("internal_hr");
  const [selectedOffer, setSelectedOffer] = useState(offerId);
  const [owner, setOwner] = useState("");
  const [filter, setFilter] = useState("active");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => { const token = auth.getAccess(); if (!token) return; try { const [records, available] = await Promise.all([journeysApi.cases(token), journeysApi.offers(token)]); setCases(records); setOffers(available); } catch (e) { setError(errorMessage(e)); } finally { setLoading(false); } }, []);
  useEffect(() => { void load(); const token = auth.getAccess(); if (!token) return; journeysApi.team(token).then(setTeam).catch(e => setError(errorMessage(e))); journeysApi.templates(token).then(setTemplates).catch(e => setError(errorMessage(e))); authApi.me(token).then(me => setOwner(me.id)).catch(e => setError(errorMessage(e))); authApi.workspace(token).then(workspace => setTemplate(workspace?.type === "zeitarbeit" ? "staffing" : workspace?.type === "recruiter_agency" ? "agency" : "internal_hr")).catch(() => {}); }, [load]);
  async function start(e: React.FormEvent) { e.preventDefault(); const token = auth.getAccess(); if (!token) return; setBusy(true); setError(""); try { await journeysApi.start(token, selectedOffer, template, owner); setSelectedOffer(""); await load(); } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); } }
  const pending = offers.filter(offer => offer.status === "accepted" && !cases.some(c => c.offer_id === offer.id));
  const shown = cases.filter(c => filter === "all" || (filter === "done" ? c.completed === c.total : c.completed < c.total));
  return <div className="mx-auto max-w-6xl space-y-6 px-4 py-8 sm:px-8"><header className="flex flex-wrap items-start justify-between gap-4"><div><p className="mb-2 text-sm font-medium text-blue-700">Ein guter Start ist Teamarbeit</p><h1 className="text-3xl font-semibold">Onboarding</h1><p className="mt-2 text-sm leading-6 text-slate-600">Ein klarer Plan, feste Ansprechpersonen und alle Schritte bis zum Einstieg.</p></div><Link href="/dashboard/offers" className="inline-flex min-h-11 items-center rounded-xl border bg-white px-4 text-sm">Angebote & Freigaben</Link></header>{error && <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</p>}
    {pending.length > 0 && <form onSubmit={start} className="space-y-4 rounded-2xl border border-blue-200 bg-blue-50 p-5"><h2 className="font-semibold">Angenommenes Angebot übernehmen</h2><div className="grid gap-4 sm:grid-cols-3"><label className="text-sm">Angebot<select required aria-label="Angebot" value={selectedOffer} onChange={e => setSelectedOffer(e.target.value)} className="mt-2 min-h-11 w-full rounded-xl border bg-white px-3"><option value="">Angebot auswählen</option>{pending.map(offer => <option key={offer.id} value={offer.id}>{offer.person_name} · {offer.title}</option>)}</select></label><label className="text-sm">Prozessvorlage<select aria-label="Prozessvorlage" value={template} onChange={e => setTemplate(e.target.value)} className="mt-2 min-h-11 w-full rounded-xl border bg-white px-3">{templates.map(item => <option key={item.key} value={item.key}>{item.title}</option>)}</select></label><label className="text-sm">Verantwortlich<select required aria-label="Verantwortlich" value={owner} onChange={e => setOwner(e.target.value)} className="mt-2 min-h-11 w-full rounded-xl border bg-white px-3"><option value="">Person auswählen</option>{team.map(member => <option key={member.id} value={member.id}>{member.full_name}</option>)}</select></label></div><ul className="flex flex-wrap gap-2">{templates.find(item => item.key === template)?.steps.map(step => <li key={step.title} className="rounded-lg bg-white px-3 py-2 text-xs text-slate-700">{step.title}</li>)}</ul><button disabled={busy || !selectedOffer} className="min-h-11 rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white disabled:opacity-50">Onboarding starten</button></form>}
    <div className="flex flex-wrap gap-2" aria-label="Onboarding filtern">{[["active", "Laufend"], ["done", "Abgeschlossen"], ["all", "Alle"]].map(([value, label]) => <button key={value} aria-pressed={filter === value} onClick={() => setFilter(value)} className={`min-h-11 rounded-xl border px-4 text-sm ${filter === value ? "border-blue-200 bg-blue-50 text-blue-800" : "bg-white text-slate-600"}`}>{label}</button>)}</div>
    {loading ? <p role="status">Onboarding wird geladen …</p> : shown.length ? <div className="space-y-5">{shown.map(journey => <OnboardingCard key={journey.id} journey={journey} team={team} privateView refresh={load} />)}</div> : <div className="rounded-2xl border bg-white p-10 text-center"><h2 className="font-semibold">Hier ist alles vorbereitet für den nächsten Einstieg</h2><p className="mt-2 text-sm text-slate-600">Sobald ein Angebot angenommen wurde, kannst du einen passenden Onboarding-Prozess starten.</p></div>}
  </div>;
}
