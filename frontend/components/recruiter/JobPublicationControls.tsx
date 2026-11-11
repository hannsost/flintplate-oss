"use client";

import { useState } from "react";
import { ApiError, recruiterApi, type JobPosting } from "@/lib/api";
import { auth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { JobForm } from "@/components/recruiter/JobForm";

export function jobPublicationLabel(job: JobPosting) {
  if (job.publication_status === "archived") return "Archiviert";
  if (job.publication_status === "draft") return "Entwurf";
  return job.expires_at && new Date(job.expires_at) <= new Date() ? "Abgelaufen" : "Veröffentlicht";
}

export function JobPublicationControls({ job, onChange, imported = false }: {
  job: JobPosting; onChange: (job: JobPosting) => void; imported?: boolean;
}) {
  const [action, setAction] = useState<"publish" | "withdraw" | "archive" | null>(null);
  const [editingImport, setEditingImport] = useState(false);
  const [expires, setExpires] = useState(() => new Date(Date.now() + 30 * 86400000).toISOString().slice(0, 10));
  const [confirmed, setConfirmed] = useState(false);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [events, setEvents] = useState<Awaited<ReturnType<typeof recruiterApi.publicationEvents>> | null>(null);
  const label = jobPublicationLabel(job);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const token = auth.getAccess();
    if (!token || !action) return;
    setBusy(true); setError("");
    try {
      const updated = await recruiterApi.publication(token, job, action, {
        ...(action === "publish" ? { expires_at: new Date(`${expires}T23:59:59`).toISOString(), rights_confirmed: confirmed } : {}),
        ...(note.trim() ? { note: note.trim() } : {}),
      }, imported);
      onChange(updated); setAction(null); setConfirmed(false); setEvents(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Änderung konnte nicht gespeichert werden.");
    } finally { setBusy(false); }
  }

  async function history() {
    if (events) { setEvents(null); return; }
    const token = auth.getAccess(); if (!token) return;
    try { setEvents(await recruiterApi.publicationEvents(token, job.id)); }
    catch { setError("Verlauf konnte nicht geladen werden."); }
  }

  return <section aria-label={`Veröffentlichung ${job.title}`} className="mt-4 space-y-3 border-t border-gray-100 pt-3">
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className={`rounded-full px-2.5 py-1 font-medium ${label === "Veröffentlicht" ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-700"}`}>{label}</span>
      {job.publication_status === "published" && job.expires_at && <span className="text-gray-600">Sichtbar bis {new Date(job.expires_at).toLocaleString("de-DE")}</span>}
      {job.publication_status !== "archived" && <>
        <Button size="sm" variant="outline" disabled={busy} onClick={() => { setAction("publish"); setError(""); }}>{label === "Veröffentlicht" ? "Verlängerung prüfen" : "Veröffentlichung prüfen"}</Button>
        {job.publication_status === "published" && <Button size="sm" variant="outline" disabled={busy} onClick={() => setAction("withdraw")}>Zurückziehen</Button>}
        <Button size="sm" variant="outline" disabled={busy} onClick={() => setAction("archive")}>Archivieren</Button>
      </>}
      {!imported && <Button size="sm" variant="ghost" onClick={history}>Verlauf</Button>}
      {imported && job.publication_status !== "archived" && <Button size="sm" variant="outline" onClick={() => { setEditingImport(value => !value); setAction(null); }}>Angaben bearbeiten</Button>}
    </div>
    {editingImport && <JobForm initial={job} submitLabel="Importentwurf speichern" onSubmit={async data => {
      const token = auth.getAccess(); if (!token) return;
      onChange(await recruiterApi.updateImportedJob(token, job, data)); setEditingImport(false);
    }} />}
    {action && <form onSubmit={submit} className="space-y-3 rounded-lg bg-gray-50 p-4">
      <h3 className="font-semibold">{action === "publish" ? "Veröffentlichung prüfen" : action === "archive" ? "Inserat archivieren" : "Veröffentlichung zurückziehen"}</h3>
      {action === "publish" ? <>
        <p className="text-sm text-gray-700 whitespace-pre-wrap break-words">{job.description || "Bitte zuerst eine Stellenbeschreibung ergänzen."}</p>
        {imported && job.url && <p className="break-all text-sm">Quelle: <a href={/^https?:\/\//i.test(job.url) ? job.url : undefined} target="_blank" rel="noreferrer" className="underline">{job.url}</a></p>}
        <label className="block text-sm">Sichtbar bis einschließlich
          <input type="date" required value={expires} onChange={e => setExpires(e.target.value)} className="mt-1 block rounded-md border border-gray-300 bg-white px-3 py-2" />
        </label>
        {imported && <label className="block text-sm">Nachweis der Veröffentlichungsrechte
          <textarea required maxLength={1000} value={note} onChange={e => setNote(e.target.value)} className="mt-1 w-full rounded-md border border-gray-300 p-2" />
        </label>}
        <label className="flex items-start gap-2 text-sm text-gray-800">
          <input type="checkbox" required checked={confirmed} onChange={e => setConfirmed(e.target.checked)} className="mt-1" />
          Ich habe Inhalt und Aktualität geprüft und bin zur Veröffentlichung dieser Stelle berechtigt.
        </label>
        <p className="text-xs text-gray-600">Die Stelle wird in der FlintPlate-Jobbörse sichtbar. Maximal 180 Tage; spätere Änderungen benötigen eine erneute Veröffentlichung.</p>
      </> : <p className="text-sm text-gray-700">{action === "archive" ? "Das Inserat wird dauerhaft geschlossen. Vorhandene Bewerbungen und der Verlauf bleiben zugänglich." : "Die Stelle wird sofort ausgeblendet und kann anschließend als Entwurf bearbeitet werden."}</p>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={busy}>{busy ? "Speichern…" : action === "publish" ? "Jetzt veröffentlichen" : action === "archive" ? "Archivierung bestätigen" : "Jetzt zurückziehen"}</Button>
        <Button type="button" variant="outline" disabled={busy} onClick={() => { setAction(null); setError(""); }}>Abbrechen</Button>
      </div>
    </form>}
    {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    {events && <ul className="space-y-1 text-sm text-gray-700" aria-label="Veröffentlichungsverlauf">
      {events.length === 0 && <li>Noch keine Veröffentlichungsentscheidung.</li>}
      {events.map(item => <li key={item.id}>Version {item.version} · {({ publish: "Veröffentlicht", withdraw: "Zurückgezogen", archive: "Archiviert", edit: "Bearbeitet" } as Record<string, string>)[item.action] || item.action} · {new Date(item.created_at).toLocaleString("de-DE")}{item.note && ` · ${item.note}`}</li>)}
    </ul>}
  </section>;
}
