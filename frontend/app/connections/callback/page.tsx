"use client";

import { Suspense, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { communicationApi } from "@/lib/communication";
import { errorMessage } from "@/lib/workspace";

const PENDING = "Verbindung wird abgeschlossen …";
const FAILED = "Die Verbindung wurde nicht abgeschlossen. Bitte im Arbeitsbereich erneut starten.";

function useAccessToken(): string | null | undefined {
  return useSyncExternalStore(
    onChange => {
      window.addEventListener("storage", onChange);
      return () => window.removeEventListener("storage", onChange);
    },
    () => auth.getAccess(),
    () => undefined,
  );
}

function ConnectionCallbackContent() {
  const params = useSearchParams();
  const token = useAccessToken();
  const code = params.get("code");
  const state = params.get("state");
  const urlOk = !params.has("error") && Boolean(code) && Boolean(state);
  const [outcome, setOutcome] = useState<string | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (token === undefined || started.current) return;
    const currentCode = code;
    const currentState = state;
    const currentToken = token;
    const canComplete = urlOk && Boolean(currentToken);
    started.current = true;
    if (!canComplete || !currentCode || !currentState || !currentToken) {
      if (window.location.search) {
        window.history.replaceState(null, "", "/connections/callback");
      }
      return;
    }
    communicationApi
      .callback(currentToken, currentState, currentCode)
      .then(connection => {
        window.history.replaceState(null, "", "/connections/callback");
        setOutcome(`${connection.email ?? "Dein Konto"} ist jetzt verbunden.`);
      })
      .catch(e => {
        window.history.replaceState(null, "", "/connections/callback");
        setOutcome(errorMessage(e));
      });
  }, [token, urlOk, code, state]);

  const message = outcome ?? (token !== undefined && (!urlOk || !token) ? FAILED : PENDING);

  return (
    <main className="mx-auto max-w-lg space-y-5 p-8">
      <h1 className="text-2xl font-semibold">E-Mail & Kalender</h1>
      <p role="status" className="text-sm text-slate-600">{message}</p>
      <Link href="/dashboard/connections" className="inline-flex min-h-11 items-center rounded-xl bg-blue-600 px-4 text-sm text-white">
        Zurück zu den Verbindungen
      </Link>
    </main>
  );
}

export default function ConnectionCallback() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-lg space-y-5 p-8">
          <h1 className="text-2xl font-semibold">E-Mail & Kalender</h1>
          <p role="status" className="text-sm text-slate-600">{PENDING}</p>
        </main>
      }
    >
      <ConnectionCallbackContent />
    </Suspense>
  );
}
