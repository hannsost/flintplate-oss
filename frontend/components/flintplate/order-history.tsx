"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { cancelledOrderCents, correctedOrderCents } from "@/lib/flintplate-cancellations";
import { auth } from "@/lib/auth";
import { AUTH_CHANGED_EVENT } from "@/lib/flintplate-drafts";
import { day, labels, message, money, time, venueApi, type Order, type Resource, type Venue } from "@/lib/flintplate";
import type { OrderHistoryPage } from "@/lib/flintplate-history";
import { Empty, Field, Tag } from "./shared";

export function OrderHistory({ venue, resources, onOpen, onCash }: { venue: Venue; resources: Resource[]; onOpen: (order: Order) => void; onCash: (order: Order) => void }) {
  const [query, setQuery] = useState("");
  const [date, setDate] = useState("");
  const [table, setTable] = useState("");
  const [filter, setFilter] = useState("");
  const [rows, setRows] = useState<Order[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const version = useRef(0);
  const active = useRef(false);
  const visited = useRef(new Set<string>());
  const load = useCallback(async (before: string | null, filters: string) => {
    const id = ++version.current;
    const user = auth.getAccess();
    setBusy(true); setError("");
    try {
      const page = await venueApi<OrderHistoryPage>(venue.id, `/order-history?limit=50${filters}${before ? `&before=${encodeURIComponent(before)}` : ""}`);
      if (!active.current || version.current !== id || auth.getAccess() !== user) return;
      if (page.has_more && (!page.next_before || page.next_before === before || visited.current.has(page.next_before))) throw new Error("Die nächste Bonseite konnte nicht sicher bestimmt werden. Bitte Suche erneut starten.");
      if (page.next_before) visited.current.add(page.next_before);
      setRows(previous => before ? [...new Map([...previous, ...page.items].map(order => [order.id, order])).values()] : page.items);
      setCursor(page.next_before); setMore(page.has_more);
    } catch (cause) { if (active.current && version.current === id && auth.getAccess() === user) setError(message(cause)); }
    finally { if (active.current && version.current === id) setBusy(false); }
  }, [venue.id]);
  useEffect(() => {
    active.current = true;
    const clear = () => { version.current++; setRows([]); setMore(false); setBusy(false); setError("Bitte erneut persönlich anmelden."); };
    window.addEventListener(AUTH_CHANGED_EVENT, clear);
    const storage = (event: StorageEvent) => { if (event.key?.includes("token") || event.key === null) clear(); };
    window.addEventListener("storage", storage);
    void Promise.resolve().then(() => load(null, ""));
    return () => { active.current = false; window.removeEventListener(AUTH_CHANGED_EVENT, clear); window.removeEventListener("storage", storage); };
  }, [load]);
  return <section className="fp-panel">
    <div className="fp-section-head"><div><h2>Bonhistorie</h2><p>Offene, bezahlte und stornierte Bons – auch aus früheren Betriebstagen.</p></div><Tag>{rows.length} geladen</Tag></div>
    <form className="fp-history-search" onSubmit={event => { event.preventDefault(); const params = new URLSearchParams(); if (query.trim()) params.set("q", query.trim()); if (date) params.set("day", date); if (table) params.set("table_id", table); const next = params.size ? `&${params}` : ""; visited.current.clear(); setFilter(next); setRows([]); setMore(false); void load(null, next); }}>
      <Field label="Bonnummer suchen"><input value={query} onChange={event => setQuery(event.target.value)} maxLength={80} placeholder="z. B. FP-1042" /></Field>
      <Field label={`Betriebstag (${venue.timezone})`}><input type="date" value={date} onChange={event => setDate(event.target.value)} /></Field>
      <Field label="Tisch / Aktivität filtern"><select value={table} onChange={event => setTable(event.target.value)}><option value="">Alle</option>{resources.map(resource => <option key={resource.id} value={resource.id}>{resource.name}</option>)}</select></Field>
      <button className="fp-button" disabled={busy}><Search size={17} /> Bons suchen</button>
    </form>
    {error && <p role="alert" className="fp-notice error">{error}</p>}
    {rows.map(order => <article className="fp-history-order" key={order.id}>
      <div><strong>{order.number}</strong><small>{day(order.created_at, venue.timezone)} · {time(order.created_at, venue.timezone)} · {resources.find(resource => resource.id === order.table_id)?.name ?? (order.fulfillment === "takeaway" ? "To go" : "Ohne Tisch")}</small><small>{order.lines.map(line => `${line.quantity}× ${line.name}`).join(", ")}</small></div>
      <div><strong>{money(correctedOrderCents(order))}</strong>{cancelledOrderCents(order)>0&&<small>Original {money(order.total_cents+order.tip_cents)} · {money(cancelledOrderCents(order))} storniert</small>}<Tag>{labels[order.status] ?? order.status}</Tag><small>{labels[order.payment_status]??order.payment_status}</small></div>
      <div className="fp-inline wrap"><button className="fp-button" onClick={() => onOpen(order)} aria-label={`Bon und Verlauf ${order.number}`}>Bon & Verlauf</button><button className="fp-button" onClick={() => onCash(order)} aria-label={`Zahlungen für ${order.number}`}>Zahlungen ansehen</button></div>
    </article>)}
    {!busy && !error && !rows.length && <Empty title="Keine passenden Bons">Bonnummer, Betriebstag oder Tischfilter anpassen.</Empty>}
    {busy && <p role="status">Bonhistorie wird geladen …</p>}
    {more && <button className="fp-button wide" disabled={busy} onClick={() => void load(cursor, filter)}>Weitere Bons laden</button>}
  </section>;
}
