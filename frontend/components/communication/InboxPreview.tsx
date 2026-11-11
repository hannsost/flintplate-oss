"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Inbox, RefreshCw } from "lucide-react";
import { auth } from "@/lib/auth";
import { communicationApi, type Connection, type InboxRead, type Provider } from "@/lib/communication";
import { errorMessage } from "@/lib/workspace";

export function InboxPreview({ personId, connections, reply }: { personId: string; connections: Connection[]; reply: (subject: string) => void }) {
  const [data, setData] = useState<InboxRead | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  const connected = connections.filter(item => item.connected);
  const key = connected.map(item => `${item.provider}:${item.email}`).join("|");
  useEffect(() => { generation.current++; setData(null); setError(""); setBusy(false); }, [personId, key]);
  async function load(provider: Provider) {
    const token = auth.getAccess(); if (!token) return;
    const current = ++generation.current;
    setBusy(true); setError(""); setData(null);
    try { const result = await communicationApi.inbox(token, personId, provider); if (generation.current === current) setData(result); }
    catch (e) { if (generation.current === current) setError(errorMessage(e)); }
    finally { if (generation.current === current) setBusy(false); }
  }
  return <section aria-label="Privater Posteingang zur Person" className="space-y-4 rounded-2xl border bg-white p-5"><div className="flex items-center gap-3"><Inbox size={21} className="text-blue-600" aria-hidden="true" /><h2 className="font-semibold">Eingegangene Nachrichten</h2></div><p className="text-sm leading-6 text-slate-600">Vorschau aus deinem eigenen Postfach zu dieser Person. Diese Inhalte sind nur für dich sichtbar und werden nicht in FlintPlate gespeichert.</p>{connected.length ? <div className="flex flex-wrap gap-2">{connected.map(item => <button key={item.provider} disabled={busy} onClick={() => void load(item.provider)} className="inline-flex min-h-11 items-center gap-2 rounded-xl border px-4 text-sm text-blue-700 disabled:opacity-50"><RefreshCw size={15} />{item.provider === "google" ? "Google" : "Microsoft"}-Posteingang laden</button>)}</div> : <Link href="/dashboard/connections" className="inline-flex min-h-11 items-center text-sm font-medium text-blue-700">E-Mail-Konto verbinden</Link>}{error && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}{busy && <p role="status" className="text-sm text-slate-600">Deine Nachrichtenvorschau wird abgerufen …</p>}{data && <><p role="status" className="text-xs text-slate-600">{data.messages.length} Nachrichten aus den letzten {data.days} Tagen.{data.limited && " Weitere Nachrichten findest du direkt in deinem Postfach."}</p>{data.messages.length === 0 && <p className="rounded-xl bg-slate-50 p-4 text-sm text-slate-600">In diesem Zeitraum liegen keine eingegangenen Nachrichten dieser Person vor.</p>}<ul className="divide-y">{data.messages.map(message => <li key={message.id} className="space-y-2 py-4"><h3 className="break-words text-sm font-semibold">{message.subject}</h3><p className="break-all text-xs text-slate-600">{message.sender} · {new Date(message.received_at).toLocaleString("de-DE")}</p><p className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-700">{message.preview || "Für diese Nachricht ist keine Vorschau verfügbar."}</p><button onClick={() => reply((/^re:/i.test(message.subject) ? message.subject : `Re: ${message.subject}`).slice(0, 300))} className="min-h-11 text-sm font-medium text-blue-700">Antwort vorbereiten</button></li>)}</ul><p className="text-xs leading-5 text-slate-500">Bis zu 20 Vorschauen. Vollständige Nachrichten und Anhänge bleiben im Postfach. Eine Antwort wird als neuer prüfbarer Entwurf vorbereitet.</p></>}</section>;
}
