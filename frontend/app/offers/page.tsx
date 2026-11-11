"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Navbar } from "@/components/layout/Navbar";
import { OnboardingCard } from "@/components/journeys/OnboardingCard";
import { auth } from "@/lib/auth";
import { errorMessage } from "@/lib/workspace";
import { journeysApi, offerStatus, type Journey, type Offer } from "@/lib/journeys";

export default function MyOffers() {
  const router = useRouter();
  const [offers, setOffers] = useState<Offer[]>([]);
  const [cases, setCases] = useState<Journey[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [review, setReview] = useState<{ offer: Offer; decision: "accepted" | "declined" } | null>(null);
  const load = useCallback(async () => { const token = auth.getAccess(); if (!token) { router.replace("/login"); return; } try { const [data, onboarding] = await Promise.all([journeysApi.mine(token), journeysApi.cases(token, true)]); setOffers(data); setCases(onboarding); } catch (e) { setError(errorMessage(e)); } finally { setLoading(false); } }, [router]);
  useEffect(() => { void load(); }, [load]);
  async function decide() { const token = auth.getAccess(); if (!token || !review) return; setBusy(true); setError(""); try { await journeysApi.decide(token, review.offer, review.decision); setReview(null); await load(); } catch (e) { setError(errorMessage(e)); await load(); } finally { setBusy(false); } }
  return <div className="min-h-dvh bg-slate-50"><Navbar /><main className="mx-auto max-w-4xl space-y-6 px-4 py-8"><header><p className="mb-2 text-sm font-medium text-blue-700">Dein nächster Schritt</p><h1 className="text-3xl font-semibold">Angebote & Einstieg</h1><p className="mt-2 text-sm leading-6 text-slate-600">Prüfe deine Angebote in Ruhe. Hier findest du auch die Aufgaben für deinen Start.</p></header>{error && <p role="alert" className="rounded-xl bg-red-50 p-4 text-sm text-red-700">{error}</p>}{loading ? <p role="status">Deine Angebote werden geladen …</p> : !offers.length && <p className="rounded-2xl border bg-white p-8 text-sm text-slate-600">Sobald ein Unternehmen ein Angebot für dich bereitstellt, erscheint es hier.</p>}
    {offers.map(offer => <article key={offer.id} className="space-y-4 rounded-2xl border bg-white p-5 sm:p-7"><div className="flex flex-wrap items-start justify-between gap-3"><h2 className="text-xl font-semibold">{offer.title}</h2><span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-800">{offerStatus[offer.status]}</span></div><div className="flex flex-wrap gap-4 text-sm text-slate-600"><span>Eintritt: {new Date(`${offer.start_date}T12:00:00`).toLocaleDateString("de-DE")}</span><span>Antwort bis: {new Date(`${offer.expires_on}T12:00:00`).toLocaleDateString("de-DE")}</span></div><p className="whitespace-pre-wrap break-words rounded-xl bg-slate-50 p-4 text-sm leading-7">{offer.terms}</p>{offer.status === "shared" && (review?.offer.id === offer.id ? <section aria-label="Antwort bestätigen" className="space-y-3 rounded-xl border border-blue-200 bg-blue-50 p-4"><h3 className="font-semibold">{review.decision === "accepted" ? "Möchtest du dieses Angebot annehmen?" : "Möchtest du dieses Angebot ablehnen?"}</h3><p className="text-sm leading-6">Deine Antwort auf diese Konditionen wird gespeichert und dem Recruiting-Team angezeigt. Die Vertragsunterzeichnung wird separat mit dir abgestimmt.</p><div className="flex flex-wrap gap-2"><button disabled={busy} onClick={() => void decide()} className="min-h-11 rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white disabled:opacity-50">{review.decision === "accepted" ? "Annahme bestätigen" : "Ablehnung bestätigen"}</button><button disabled={busy} onClick={() => setReview(null)} className="min-h-11 px-3 text-sm">Weiter prüfen</button></div></section> : <div className="flex flex-wrap gap-3"><button onClick={() => setReview({ offer, decision: "accepted" })} className="min-h-11 rounded-xl bg-blue-600 px-4 text-sm font-semibold text-white">Angebot annehmen</button><button onClick={() => setReview({ offer, decision: "declined" })} className="min-h-11 rounded-xl border px-4 text-sm text-slate-600">Angebot ablehnen</button></div>)}</article>)}
    {cases.length > 0 && <section className="space-y-5"><h2 className="text-2xl font-semibold">Dein Einstieg</h2>{cases.map(journey => <OnboardingCard key={journey.id} journey={journey} refresh={load} />)}</section>}
  </main></div>;
}
