"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Archive, Eye, History, Plus, RefreshCw, Save } from "lucide-react";
import { auth } from "@/lib/auth";
import { message, venueApi, type Venue } from "@/lib/flintplate";
import type { useVenueMutation } from "@/lib/flintplate-pending";
import type { LayoutPreview, LayoutProfile, LayoutRevision } from "@/lib/flintplate-layout";
import type { Data } from "./operations";
import { Empty, Field, Loading, Modal, Tag } from "./shared";
import { FloorCanvas } from "./floor-canvas";

interface Props { venue: Venue; data: Data; roomId: string | null; mutation: ReturnType<typeof useVenueMutation>; refreshing: boolean; onClose: () => void }
type Screen = { kind: "list" } | { kind: "save"; profile: LayoutProfile | null } | { kind: "preview"; profile: LayoutProfile; value: LayoutPreview };

export function LayoutProfiles({ venue, data, roomId, mutation, refreshing, onClose }: Props) {
  const [profiles, setProfiles] = useState<LayoutProfile[] | null>(null), [archived, setArchived] = useState(false);
  const [screen, setScreen] = useState<Screen>({ kind: "list" });
  const [name, setName] = useState(""), [saveRoom, setSaveRoom] = useState(roomId ?? "");
  const [history, setHistory] = useState<Record<string, LayoutRevision[]>>({}), [moreHistory, setMoreHistory] = useState<Record<string, boolean>>({});
  const [reading, setReading] = useState(false), [error, setError] = useState("");
  const mounted = useRef(true), generation = useRef(0), loadVersion = useRef(0);
  const locked = !mutation.ready || mutation.busy || !!mutation.pending || mutation.blocked;
  const roomName = (id: string | null) => id ? data.rooms.find(room => room.id === id)?.name ?? "Nicht mehr vorhandener Raum" : "Ganzer Betrieb";
  const load = useCallback(async () => {
    const request = ++loadVersion.current, user = auth.getUser(), scope = JSON.stringify([user?.tenant_id, user?.sub]);
    const next = await venueApi<LayoutProfile[]>(venue.id, `/layout/profiles?include_archived=${archived}`);
    const current = auth.getUser();
    if (mounted.current && request === loadVersion.current && scope === JSON.stringify([current?.tenant_id, current?.sub])) setProfiles(next);
  }, [venue.id, archived]);
  useEffect(() => { mounted.current = true; void load().catch(cause => { if (mounted.current) setError(message(cause)); }); return () => { mounted.current = false; }; }, [load]);

  async function read<T>(work: () => Promise<T>, done: (value: T) => void) {
    if (reading) return;
    const request = ++generation.current, user = auth.getUser(), scope = JSON.stringify([user?.tenant_id, user?.sub]);
    setReading(true); setError("");
    const active = () => { const user = auth.getUser(); return mounted.current && request === generation.current && scope === JSON.stringify([user?.tenant_id, user?.sub]); };
    try { const value = await work(); if (active()) done(value); }
    catch (cause) { if (active()) setError(message(cause)); }
    finally { if (active()) setReading(false); }
  }
  async function preview(profile: LayoutProfile, revisionId?: string) {
    await read(() => venueApi<LayoutPreview>(venue.id, `/layout/profiles/${profile.id}/preview`, "POST", { version: profile.version, ...(revisionId ? { revision_id: revisionId } : {}) }), value => setScreen({ kind: "preview", profile, value }));
  }
  async function revisions(profile: LayoutProfile, nextPage = false) {
    const before = nextPage ? history[profile.id]?.at(-1)?.version : undefined;
    await read(() => venueApi<LayoutRevision[]>(venue.id, `/layout/profiles/${profile.id}/versions?limit=20${before ? `&before_version=${before}` : ""}`), rows => { setHistory(previous => ({ ...previous, [profile.id]: nextPage ? [...(previous[profile.id] ?? []), ...rows] : rows })); setMoreHistory(previous => ({ ...previous, [profile.id]: rows.length === 20 })); });
  }
  function edit(profile: LayoutProfile | null) { setName(profile?.name ?? ""); setSaveRoom(profile ? profile.room_id ?? "" : roomId ?? ""); setScreen({ kind: "save", profile }); mutation.clearError(); }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (screen.kind !== "save" || locked) return;
    const tables = data.resources.filter(resource => !saveRoom || resource.room_id === saveRoom).map(resource => ({ table_id: resource.id, version: resource.version })).sort((left, right) => left.table_id.localeCompare(right.table_id));
    if (await mutation.send("/layout/profiles", { profile_id: screen.profile?.id ?? null, expected_version: screen.profile?.version ?? 0, name: name.trim(), room_id: saveRoom || null, tables }, screen.profile ? "Neue Grundrissversion speichern" : "Grundrissprofil speichern")) { setScreen({ kind: "list" }); await load().catch(cause => setError(message(cause))); }
  }
  async function archive(profile: LayoutProfile) {
    if (await mutation.send(`/layout/profiles/${profile.id}/archive`, { version: profile.version, archived: !profile.archived }, profile.archived ? "Grundrissprofil reaktivieren" : "Grundrissprofil archivieren")) await load().catch(cause => setError(message(cause)));
  }
  async function apply() {
    if (screen.kind !== "preview" || locked || screen.value.blocking_reasons.length) return;
    const value = screen.value;
    if (await mutation.send(`/layout/profiles/${value.profile_id}/apply`, { version: value.profile_version, revision_id: value.revision_id, fingerprint: value.fingerprint }, `Grundriss ${value.name} anwenden`)) { setScreen({ kind: "list" }); await load().catch(cause => setError(message(cause))); }
  }
  const visible = profiles?.filter(profile => !roomId || profile.room_id === null || profile.room_id === roomId) ?? [];
  const value = screen.kind === "preview" ? screen.value : null;

  return <Modal title={screen.kind === "save" ? "Grundrissprofil speichern" : screen.kind === "preview" ? "Grundriss vor dem Anwenden prüfen" : "Grundrissprofile"} onClose={onClose}>
    {(error || mutation.error) && <p className="fp-notice error" role="alert">{error || mutation.error}</p>}
    {refreshing && <p className="fp-notice" role="status">Grundriss wird aktualisiert. Verschieben ist danach wieder möglich.</p>}
    {mutation.pending && <p className="fp-notice" role="status">{mutation.pending.label}: {mutation.busy ? "Wird gespeichert und aktualisiert …" : "Bestätigung steht aus."}<button disabled={mutation.busy || mutation.blocked} onClick={async () => { if (await mutation.retry()) { await load().catch(cause => setError(message(cause))); setScreen({ kind: "list" }); } }}>Grundrissvorgang erneut prüfen</button></p>}
    {screen.kind !== "list" && <button className="fp-button" disabled={reading || mutation.busy} onClick={() => setScreen({ kind: "list" })}>Zur Profilübersicht</button>}
    {screen.kind === "list" && <>
      <p className="fp-description">Anordnungen für Alltag, Veranstaltungen oder Terrasse speichern. Profile verwenden vorhandene Tische und Aktivitäten.</p>
      <div className="fp-inline wrap"><button className="fp-button primary" disabled={locked || data.resources.length === 0} onClick={() => edit(null)}><Plus size={16} />Aktuelle Anordnung speichern</button><button className="fp-button" disabled={reading} onClick={() => void read(load, () => undefined)}><RefreshCw size={16} />Profile aktualisieren</button></div>
      <label className="fp-check"><input type="checkbox" checked={archived} onChange={event => setArchived(event.target.checked)} />Archivierte Profile zeigen</label>
      {profiles === null ? <Loading /> : !visible.length ? <Empty title="Noch kein Grundrissprofil">Speichere eine benannte Anordnung für {roomName(roomId)}.</Empty> : visible.map(profile => <article className="fp-form-box fp-layout-profile" key={profile.id}>
        <div className="fp-section-head"><div><h3>{profile.name}</h3><p>{roomName(profile.room_id)} · {profile.table_count} Ressourcen · Version {profile.version}</p></div><Tag>{profile.archived ? "Archiviert" : "Aktiv"}</Tag></div>
        <div className="fp-inline wrap"><button className="fp-button primary" disabled={reading || profile.archived} onClick={() => void preview(profile)}><Eye size={16} />Vorschau</button><button className="fp-button" disabled={locked || profile.archived} onClick={() => edit(profile)}><Save size={16} />Aktuelle Anordnung als neue Version</button><button className="fp-button" disabled={reading} onClick={() => void revisions(profile)}><History size={16} />Versionshistorie</button><button className="fp-button" disabled={locked} onClick={() => void archive(profile)}><Archive size={16} />{profile.archived ? "Reaktivieren" : "Archivieren"}</button></div>
        {history[profile.id] && <div>{history[profile.id].map(revision => <div className="fp-list-row" key={revision.id}><div><strong>Version {revision.version} · {revision.name}</strong><small>{new Date(revision.created_at).toLocaleString("de-DE", { timeZone: venue.timezone })} · {revision.placements.length} Ressourcen{revision.archived ? " · archiviert" : ""}</small></div><button className="fp-button" disabled={reading || profile.archived} onClick={() => void preview(profile, revision.id)}>Version {revision.version} ansehen</button></div>)}{moreHistory[profile.id] && <button className="fp-button" disabled={reading} onClick={() => void revisions(profile, true)}>Ältere Versionen laden</button>}</div>}
      </article>)}
    </>}
    {screen.kind === "save" && <form onSubmit={save}><fieldset disabled={locked} className="fp-layout-fieldset"><Field label="Profilname"><input value={name} onChange={event => setName(event.target.value)} required minLength={2} maxLength={80} placeholder="Zum Beispiel Abendservice" /></Field><Field label="Profil für"><select value={saveRoom} onChange={event => setSaveRoom(event.target.value)}><option value="">Ganzer Betrieb</option>{data.rooms.map(room => <option key={room.id} value={room.id}>{roomName(room.id)}</option>)}</select></Field><p className="fp-description">Speichert die aktuell bestätigten Positionen aller {data.resources.filter(resource => !saveRoom || resource.room_id === saveRoom).length} Ressourcen in dieser Auswahl. {screen.profile ? `Version ${screen.profile.version} bleibt in der Historie erhalten.` : "Die Anordnung erhält einen eigenen Namen."}</p><button className="fp-button primary wide" disabled={!data.resources.some(resource => !saveRoom || resource.room_id === saveRoom)}><Save size={16} />Profil verbindlich speichern</button></fieldset></form>}
    {value && <>
      <h3>{value.name} · Anordnung aus Version {value.snapshot_version}</h3><p className="fp-description">{value.rows.filter(row => row.changed).length} Positionen ändern sich. Die Vorschau ist noch nicht angewendet.</p>
      {value.blocking_reasons.map(reason => <p className="fp-notice error" key={reason}>{reason}</p>)}
      <div inert aria-hidden="true">{[...new Set(value.rows.map(row => row.saved.room_id))].map(id => <FloorCanvas key={id ?? "all"} label={id ? roomName(id) : "Ohne Raumzuordnung"} compact editing={false} snap={false} disabled selectedId="" onSelect={() => undefined} onMove={async () => undefined} resources={value.rows.filter(row => row.saved.room_id === id).flatMap(row => { const resource = data.resources.find(resource => resource.id === row.table_id); return resource ? [{ resource: { ...resource, x: row.saved.x, y: row.saved.y }, state: row.changed ? "soon" : "free", note: row.changed ? "Neue Position" : "Unverändert" }] : []; })} />)}</div>
      <details><summary>Ressourcen und Änderungen ({value.rows.length})</summary>{[...new Set(value.rows.map(row => row.saved.room_id))].map(id => <section className="fp-form-box fp-layout-profile" key={id ?? "unassigned"}><h3>{id ? roomName(id) : "Ohne Raumzuordnung"}</h3>{value.rows.filter(row => row.saved.room_id === id).map(row => <p key={row.table_id}>{row.name} · {row.current ? row.changed ? "Position wird geändert" : "Unverändert" : "Ressource fehlt"}</p>)}</section>)}{value.added_table_ids.map(id => <p key={id}>{data.resources.find(resource => resource.id === id)?.name ?? "Neue Ressource"} · nicht im gespeicherten Profil</p>)}</details>
      <div className="fp-inline wrap"><button className="fp-button" disabled={reading || mutation.busy} onClick={() => { if (screen.kind === "preview") void preview(screen.profile, value.revision_id); }}><RefreshCw size={16} />Vorschau erneuern</button><button className="fp-button primary" disabled={locked || value.blocking_reasons.length > 0} onClick={() => void apply()}>Diese Anordnung anwenden</button></div>
      <p className="fp-description">Wendet die gezeigten Positionen auf die vorhandenen Ressourcen an. Eine ältere Anordnung wird mit ihrer konkreten Version protokolliert.</p>
    </>}
  </Modal>;
}
