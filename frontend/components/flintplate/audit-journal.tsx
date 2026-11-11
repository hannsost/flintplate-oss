"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Download, RefreshCw, ShieldCheck } from "lucide-react";
import { auth } from "@/lib/auth";
import { AUTH_CHANGED_EVENT } from "@/lib/flintplate-drafts";
import { auditPage, type AuditEvent } from "@/lib/flintplate-history";
import { day, message, time, type Member, type Venue } from "@/lib/flintplate";
import { Empty, Tag } from "./shared";

export function AuditJournal({ venue, members }: { venue: Venue; members: Member[] }) {
  const [rows, setRows] = useState<AuditEvent[]>([]);
  const [through, setThrough] = useState<number | null>(null);
  const [after, setAfter] = useState(0);
  const [more, setMore] = useState(false);
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const version = useRef(0);
  const active = useRef(false);
  const load = useCallback(async (cursor = 0, end?: number) => {
    const id = ++version.current, token = auth.getAccess();
    setBusy(true); setError("");
    try {
      const page = await auditPage(venue.id, cursor, end);
      if (!active.current || id !== version.current || auth.getAccess() !== token) return;
      setRows(current => cursor ? [...current, ...page.items] : page.items);
      setThrough(page.through_sequence); setAfter(page.next_after); setMore(page.has_more);
    } catch (cause) { if (active.current && id === version.current && auth.getAccess() === token) setError(message(cause)); }
    finally { if (active.current && id === version.current) setBusy(false); }
  }, [venue.id]);
  useEffect(() => {
    active.current = true;
    const clear = () => { version.current++; setRows([]); setThrough(null); setMore(false); setBusy(false); setExporting(false); setError("Bitte erneut persönlich anmelden."); };
    const storage = (event: StorageEvent) => { if (event.key?.includes("token") || event.key === null) clear(); };
    window.addEventListener(AUTH_CHANGED_EVENT, clear); window.addEventListener("storage", storage);
    if (venue.role === "manager") void Promise.resolve().then(() => load());
    return () => { active.current = false; window.removeEventListener(AUTH_CHANGED_EVENT, clear); window.removeEventListener("storage", storage); };
  }, [load, venue.role]);
  async function download() {
    if (through === null || busy || exporting) return;
    const token = auth.getAccess(), id = version.current;
    setExporting(true); setError(""); setNotice("");
    try {
      const items: AuditEvent[] = [];
      let cursor = 0;
      for (;;) {
        const page = await auditPage(venue.id, cursor, through);
        if (!active.current || version.current !== id || auth.getAccess() !== token) return;
        items.push(...page.items);
        setNotice(`${items.length} Journalereignisse für den Export geladen …`);
        if (!page.has_more) break;
        cursor = page.next_after;
      }
      const data = { venue_id: venue.id, through_sequence: through, items };
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const link = document.createElement("a"); link.href = url; link.download = "flintplate-journal.json"; link.click(); URL.revokeObjectURL(url);
      setNotice(`Journal bis Sequenz ${through} vollständig heruntergeladen: ${items.length} Ereignisse.`);
    } catch (cause) { if (active.current && auth.getAccess() === token) setError(message(cause)); }
    finally { if (active.current && auth.getAccess() === token) setExporting(false); }
  }
  if (venue.role !== "manager") return null;
  return <section className="fp-panel">
    <div className="fp-section-head"><div><ShieldCheck size={25} /><h2>Journal & Exporte</h2><p>Vorgänge mit Person, Zeitpunkt und ursprünglichem Inhalt. Der geladene Endstand bleibt beim Blättern und Export unverändert.</p></div>{through !== null && <Tag>Endstand {through}</Tag>}</div>
    <div className="fp-inline wrap"><button className="fp-button" disabled={busy || exporting} onClick={() => { setNotice(""); void Promise.resolve().then(() => load()); }}><RefreshCw size={16} /> Neuen Endstand laden</button><button className="fp-button" disabled={busy || exporting || through === null} onClick={() => void download()}><Download size={16} /> Journal vollständig exportieren</button></div>
    {error && <p role="alert" className="fp-notice error">{error}</p>}{notice && <p role="status" className="fp-notice">{notice}</p>}
    {rows.map(row => <details className="fp-run" key={row.sequence}><summary><strong>#{row.sequence} · {row.kind}</strong><span>{day(row.created_at, venue.timezone)} · {time(row.created_at, venue.timezone)} · {row.actor_id ? members.find(member => member.user_id === row.actor_id)?.full_name ?? `Person ${row.actor_id.slice(0, 8)}` : row.device_id ? `Gerät ${row.device_id.slice(0, 8)}` : "System"}</span></summary><p>Bezug: {row.aggregate_id}</p><pre className="fp-audit-payload">{JSON.stringify(row.payload, null, 2)}</pre><small>Auditfolge: {row.audit_sequence ?? "nicht vorhanden"}{row.event_hash ? ` · Prüfsumme ${row.event_hash}` : ""}</small></details>)}
    {busy && <p role="status">Journal wird geladen …</p>}{!rows.length && !busy && !error && <Empty title="Noch keine Journalereignisse" />}
    {more && <button className="fp-button wide" disabled={busy || exporting} onClick={() => void load(after, through ?? undefined)}>Weitere Journalereignisse laden</button>}
    <p className="fp-description">Ein Journalexport ist kein DSFinV-K-Export. Fiskalisierung und Zielsysteme müssen gesondert eingerichtet und abgenommen werden.</p>
  </section>;
}
