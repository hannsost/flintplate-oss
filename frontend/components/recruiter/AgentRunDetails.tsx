"use client";

import { useEffect, useState } from "react";
import { auth } from "@/lib/auth";
import { agentApi, type AgentEvent, type AgentOptions, type AgentRun } from "@/lib/agents";

const labels: Record<string, string> = { assigned: "Beauftragt", prepared: "Ergebnis vorbereitet", approved: "Freigegeben", rejected: "Verworfen", cancelled: "Abgebrochen", blocked: "Gesperrt" };
const fields = { title: "Stelle", company: "Unternehmen", description: "Beschreibung", location: "Arbeitsort", skills: "Anforderungen", salary_min: "Gehaltsuntergrenze", salary_max: "Gehaltsobergrenze" };

export function AgentRunDetails({ run, members }: { run: AgentRun; members: AgentOptions["members"] }) {
  const [open, setOpen] = useState(false);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!open) return;
    const token = auth.getAccess();
    if (!token) return;
    let active = true;
    void agentApi.events(token, run.id).then(rows => { if (active) { setEvents(rows); setError(""); } }).catch(() => {
      if (active) setError("Verlauf konnte nicht geladen werden. Schließe und öffne die Details erneut.");
    });
    return () => { active = false; };
  }, [open, run.id, run.version]);
  const person = (id: string | null) => members.find(member => member.id === id)?.name || "Person nicht mehr verfügbar";
  return <details className="rounded-lg border border-gray-200 p-3 text-sm" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary className="cursor-pointer py-2 font-medium">Eingabestand und Verlauf</summary>
    <p className="my-3 text-gray-600">Beauftragt von {person(run.delegated_by)} · Prüfung durch {person(run.reviewer_id)}</p>
    <p className="mb-3 text-gray-600">Gespeicherte Angaben zum Zeitpunkt der Beauftragung. Spätere Stellenänderungen sind in diesem Stand nicht enthalten.</p>
    <dl className="space-y-3">{Object.entries(fields).map(([key, label]) => <div key={key}>
      <dt className="font-medium">{label}</dt>
      <dd className="whitespace-pre-wrap break-words text-gray-700">{run.source[key] || "Nicht angegeben"}</dd>
    </div>)}</dl>
    {error && <p role="alert" className="mt-4 text-red-700">{error}</p>}
    <ol aria-label="Auftragsverlauf" className="mt-4 space-y-2 border-t pt-4">{events.map((event, index) => <li key={index} className="break-words">
      {labels[event.action] || event.action} · {event.actor_id === null && ["prepared", "blocked"].includes(event.action) ? "System" : person(event.actor_id)} · <time dateTime={event.created_at}>{new Date(event.created_at).toLocaleString("de-DE")}</time>
    </li>)}</ol>
  </details>;
}
