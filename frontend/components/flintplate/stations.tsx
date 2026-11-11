"use client";
import { newRequestId } from "@/lib/flintplate-uuid";


import { useEffect, useRef, useState } from "react";
import { Plus, Settings2 } from "lucide-react";
import { ApiError } from "@/lib/api";
import { auth } from "@/lib/auth";
import { AUTH_CHANGED_EVENT } from "@/lib/flintplate-drafts";
import { message, venueApi, type OperatingStation, type Order, type Station, type Venue } from "@/lib/flintplate";
import { readStationMutation, stationCommandForSend, stationKindLabels, stationTabs, STATION_FILTER_PREFIX, STATION_PENDING_PREFIX, type StationMutation } from "@/lib/flintplate-stations";
import type { Action } from "./operations";
import { Field, Modal, Tag } from "./shared";

function scopeFor(venueId: string, prefix: string) {
  if (typeof window === "undefined") return null;
  try {
    const user = auth.getUser();
    return user ? prefix + encodeURIComponent(JSON.stringify([user.tenant_id, user.sub, venueId])) : null;
  } catch { return null; }
}

export function useStationFilter(venueId: string, stations: OperatingStation[], orders: Order[]) {
  const [selected, setSelected] = useState("all");
  const [notice, setNotice] = useState("");
  const scope = useRef<string | null>(null);
  const tabs = stationTabs(stations, orders);
  useEffect(() => {
    const sync = () => {
      scope.current = scopeFor(venueId, STATION_FILTER_PREFIX);
      try {
        const value = scope.current ? localStorage.getItem(scope.current) : null;
        setSelected(value && /^[a-z][a-z0-9_]{0,39}$/.test(value) ? value : "all");
        setNotice("");
      } catch { setSelected("all"); setNotice("Stationsauswahl wird auf diesem Gerät nicht gespeichert."); }
    };
    sync();
    window.addEventListener(AUTH_CHANGED_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => { scope.current = null; window.removeEventListener(AUTH_CHANGED_EVENT, sync); window.removeEventListener("storage", sync); };
  }, [venueId]);
  const available = tabs.some(tab => tab.code === selected);
  function choose(code: string) {
    if (!tabs.some(tab => tab.code === code)) return;
    const current = scopeFor(venueId, STATION_FILTER_PREFIX);
    if (!current || current !== scope.current) return;
    setSelected(code);
    try { localStorage.setItem(current, code); setNotice(""); }
    catch { setNotice("Auswahl gilt jetzt; sie konnte auf diesem Gerät nicht gespeichert werden."); }
  }
  return { station: available ? selected : "all", tabs, choose, notice: !available ? "Diese Station ist nicht mehr verfügbar. Alle Stationen werden angezeigt." : notice };
}

export function StationsButton({ venue, stations, act }: { venue: Venue; stations: OperatingStation[]; act: Action }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<OperatingStation | "new" | null>(null);
  const [pending, setPending] = useState<StationMutation | null>(null);
  const [error, setError] = useState("");
  const [invalidPending, setInvalidPending] = useState(false);
  const [busy, setBusy] = useState(false);
  const working = useRef(false);
  const scope = useRef<string | null>(null);

  useEffect(() => {
    const sync = () => {
      scope.current = scopeFor(venue.id, STATION_PENDING_PREFIX);
      setEditing(null);
      try {
        const raw = scope.current ? localStorage.getItem(scope.current) : null;
        setPending(raw ? readStationMutation(raw) : null);
        setInvalidPending(false);
        setError("");
      } catch (caught) { setPending(null); setInvalidPending(true); setError(message(caught)); }
    };
    sync();
    window.addEventListener(AUTH_CHANGED_EVENT, sync);
    window.addEventListener("storage", sync);
    return () => { scope.current = null; window.removeEventListener(AUTH_CHANGED_EVENT, sync); window.removeEventListener("storage", sync); };
  }, [venue.id]);

  async function send(command: StationMutation) {
    if (working.current || invalidPending) return;
    const activeScope = scopeFor(venue.id, STATION_PENDING_PREFIX);
    if (!activeScope || activeScope !== scope.current) return;
    let retry = false;
    try {
      const raw = localStorage.getItem(activeScope);
      if (raw) setPending(readStationMutation(raw));
      const resolved = stationCommandForSend(raw, command);
      command = resolved.command;
      retry = resolved.retry;
      localStorage.setItem(activeScope, JSON.stringify(command));
      setPending(command);
    } catch (caught) { setError(`Stationsänderung wurde nicht gesendet. ${message(caught)}`); return; }
    working.current = true;
    setBusy(true);
    setError("");
    const sameUser = () => scope.current === activeScope && scopeFor(venue.id, STATION_PENDING_PREFIX) === activeScope;
    const confirmed = () => {
      if (!sameUser()) return;
      const raw = localStorage.getItem(activeScope);
      if (raw && readStationMutation(raw).body.request_key !== command.body.request_key) return;
      localStorage.removeItem(activeScope);
      setPending(null);
      setEditing(null);
    };
    try {
      await act(async () => {
        try {
          await venueApi<OperatingStation>(venue.id, command.kind === "create" ? "/stations" : `/stations/${command.id}`, command.kind === "create" ? "POST" : "PUT", command.body);
          confirmed();
        } catch (caught) {
          if (sameUser()) setError(message(caught));
          if (!retry && caught instanceof ApiError && caught.status >= 400 && caught.status < 500 && caught.status !== 408) confirmed();
          throw caught;
        }
      }, "Stationskonfiguration gespeichert.");
    } finally { working.current = false; setBusy(false); }
  }

  if (venue.role !== "manager") return null;
  const row = editing && editing !== "new" ? editing : null;
  return <>
    <button className="fp-button" onClick={() => setOpen(true)}><Settings2 size={16} /> {pending ? "Stationsänderung prüfen" : "Stationen verwalten"}</button>
    {open && <Modal title="Betriebsstationen" onClose={() => { if (!working.current) setOpen(false); }}>
      <p className="fp-description">Artikel und Dienste bekommen eine feste Station. Der Bereich bestimmt die benötigte Qualifikation; alte Bons behalten ihre Zuordnung.</p>
      {error && <p role="alert">{error}</p>}
      {invalidPending ? <p>Der gespeicherte Vorgang muss geprüft werden, bevor eine weitere Änderung gesendet wird.</p> : pending ? <div role="status"><p>Die Änderung für „{pending.body.name}“ ist noch nicht bestätigt.</p><button className="fp-button primary" disabled={busy} onClick={() => void send(pending)}>{busy ? "Wird geprüft …" : "Mit derselben Vorgangs-ID prüfen"}</button></div> : <>
        <div className="fp-stack">{stations.map(station => <div className="fp-inline" key={station.id}><div><strong>{station.name}</strong><small> · {stationKindLabels[station.kind]}</small></div><Tag tone={station.active ? "green" : "neutral"}>{station.active ? "Aktiv" : "Inaktiv"}</Tag><button className="fp-button" onClick={() => setEditing(station)}>Bearbeiten</button></div>)}</div>
        <button className="fp-button" onClick={() => setEditing("new")}><Plus size={16} /> Station hinzufügen</button>
        {editing && <form key={row?.id ?? "new"} onSubmit={event => {
          event.preventDefault();
          const form = new FormData(event.currentTarget);
          const base = { request_key: newRequestId(), name: String(form.get("name") ?? "").trim(), sort_order: Number(form.get("sort_order")) };
          const command: StationMutation = row ? { kind: "update", id: row.id, body: { ...base, version: row.version, active: form.get("active") === "on" } } : { kind: "create", body: { ...base, kind: String(form.get("kind")) as Station } };
          void send(command);
        }}>
          <Field label="Stationsname"><input name="name" required minLength={2} maxLength={80} defaultValue={row?.name ?? ""} placeholder="Grill oder Kaltküche" /></Field>
          {row ? <p>Bereich: {stationKindLabels[row.kind]}</p> : <Field label="Bereich"><select name="kind" defaultValue="kitchen">{Object.entries(stationKindLabels).map(([kind,label]) => <option key={kind} value={kind}>{label}</option>)}</select></Field>}
          <Field label="Reihenfolge"><input name="sort_order" type="number" required min={0} max={999} defaultValue={row?.sort_order ?? 50} /></Field>
          {row && <label className="fp-check"><input name="active" type="checkbox" defaultChecked={row.active} /> Aktiv für neue Zuordnungen</label>}
          <button className="fp-button primary" disabled={busy}>Speichern</button>
        </form>}
      </>}
    </Modal>}
  </>;
}
