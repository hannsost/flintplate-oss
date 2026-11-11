"use client";
import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { communicationApi } from "@/lib/communication";
import { errorMessage } from "@/lib/workspace";

export default function ConnectionCallback() {
  const started = useRef(false);
  const [message, setMessage] = useState("Verbindung wird abgeschlossen …");
  useEffect(() => {
    if (started.current) return; started.current = true;
    const params = new URLSearchParams(window.location.search);
    window.history.replaceState(null, "", "/connections/callback");
    const token = auth.getAccess(), code = params.get("code"), state = params.get("state");
    if (params.has("error") || !code || !state || !token) { setMessage("Die Verbindung wurde nicht abgeschlossen. Bitte im Arbeitsbereich erneut starten."); return; }
    communicationApi.callback(token, state, code).then(connection => setMessage(`${connection.email ?? "Dein Konto"} ist jetzt verbunden.`)).catch(e => setMessage(errorMessage(e)));
  }, []);
  return <main className="mx-auto max-w-lg space-y-5 p-8"><h1 className="text-2xl font-semibold">E-Mail & Kalender</h1><p role="status" className="text-sm text-slate-600">{message}</p><Link href="/dashboard/connections" className="inline-flex min-h-11 items-center rounded-xl bg-blue-600 px-4 text-sm text-white">Zurück zu den Verbindungen</Link></main>;
}
