"use client";
import { newRequestId } from "./flintplate-uuid";


import { useEffect, useRef, useState } from "react";
import { ApiError } from "./api";
import { auth } from "./auth";
import { AUTH_CHANGED_EVENT } from "./flintplate-drafts";
import { message, venueApi } from "./flintplate";

export interface PendingVenueMutation { path: string; payload: Record<string, unknown>; label: string; method?: "POST" | "PUT" }
const CHANGED = "flintplate-pending-mutation-changed";

/** Persist an immutable request before sending it, scoped to the signed-in
 * principal and venue. Ambiguous responses remain retryable after a reload. */
export function useVenueMutation(venueId: string, prefix: string, allowedPath: RegExp, afterCommit?: (result: unknown) => Promise<void>) {
  const [pending, setPending] = useState<PendingVenueMutation | null>(null);
  const [busy, setBusy] = useState(false);
  const [ready, setReady] = useState(false);
  const [blocked, setBlocked] = useState(false);
  const [error, setError] = useState("");
  const current = useRef<PendingVenueMutation | null>(null);
  const inFlight = useRef(false);
  const mounted = useRef(false);
  const scope = useRef<string | null>(null);
  const keyForUser = () => {
    const user = auth.getUser();
    return user?.sub ? prefix + encodeURIComponent(JSON.stringify([user.tenant_id, user.sub, venueId])) : null;
  };

  useEffect(() => {
    mounted.current = true;
    const user = auth.getUser();
    const key = user?.sub ? prefix + encodeURIComponent(JSON.stringify([user.tenant_id, user.sub, venueId])) : null;
    scope.current = key;
    const read = () => {
      const user = auth.getUser();
      const activeKey = user?.sub ? prefix + encodeURIComponent(JSON.stringify([user.tenant_id, user.sub, venueId])) : null;
      if (!key || activeKey !== key) { current.current = null; setPending(null); setBlocked(true); setReady(true); setError("Bitte erneut persönlich anmelden."); return; }
      try {
        const raw = localStorage.getItem(key);
        const value: unknown = raw ? JSON.parse(raw) : null;
        if (value !== null && (typeof value !== "object" || !("path" in value) || typeof value.path !== "string" || !allowedPath.test(value.path) || !("label" in value) || typeof value.label !== "string" || !("payload" in value) || !value.payload || typeof value.payload !== "object" || !("request_key" in value.payload) || typeof value.payload.request_key !== "string" || !value.payload.request_key)) throw new Error("Der ausstehende Vorgang konnte nicht sicher gelesen werden. Bitte den Service kontaktieren.");
        if (value && typeof value === "object" && "method" in value && value.method !== "POST" && value.method !== "PUT") throw new Error("Der ausstehende Vorgang verwendet eine unbekannte Methode.");
        current.current = value as PendingVenueMutation | null;
        setPending(current.current);
      } catch (cause) { setBlocked(true); setError(message(cause)); }
      setReady(true);
    };
    read();
    const storage = (event: StorageEvent) => { if (event.key === key || event.key?.includes("token") || event.key === null) read(); };
    const local = (event: Event) => { if ((event as CustomEvent).detail === key) read(); };
    window.addEventListener("storage", storage);
    window.addEventListener(CHANGED, local);
    window.addEventListener(AUTH_CHANGED_EVENT, read);
    return () => { mounted.current = false; window.removeEventListener("storage", storage); window.removeEventListener(CHANGED, local); window.removeEventListener(AUTH_CHANGED_EVENT, read); };
  }, [venueId, prefix, allowedPath]);

  async function execute(request: PendingVenueMutation, retry: boolean): Promise<boolean> {
    if (inFlight.current || blocked || !ready) return false;
    const key = keyForUser();
    if (!key || key !== scope.current) { setError("Bitte erneut persönlich anmelden."); return false; }
    const serialized = JSON.stringify(request);
    try {
      const stored = localStorage.getItem(key);
      if (stored && stored !== serialized) { setError("Zuerst den bereits ausstehenden Vorgang prüfen."); window.dispatchEvent(new CustomEvent(CHANGED, { detail: key })); return false; }
      localStorage.setItem(key, serialized);
    } catch { setError("Der Browser kann diesen Vorgang nicht absichern. Bitte Speicher freigeben und erneut versuchen."); return false; }
    current.current = request;
    setPending(request);
    inFlight.current = true;
    setBusy(true);
    setError("");
    window.dispatchEvent(new CustomEvent(CHANGED, { detail: key }));
    let committed = false;
    try {
      const result = await venueApi<unknown>(venueId, request.path, request.method ?? "POST", request.payload);
      committed = true;
      if (keyForUser() !== key) return false;
      // Versioned editors must keep the durable request and write lock until
      // their authoritative read has finished, including after an exact retry.
      await afterCommit?.(result);
      if (keyForUser() !== key) return false;
      if (localStorage.getItem(key) === serialized) localStorage.removeItem(key);
      current.current = null;
      if (mounted.current) setPending(null);
      return mounted.current;
    } catch (cause) {
      if (keyForUser() !== key) return false;
      if (!committed && !retry && cause instanceof ApiError && cause.status >= 400 && cause.status < 500 && cause.status !== 408) {
        if (localStorage.getItem(key) === serialized) localStorage.removeItem(key);
        current.current = null;
        if (mounted.current) setPending(null);
      }
      if (mounted.current) setError(message(cause));
      return false;
    } finally {
      window.dispatchEvent(new CustomEvent(CHANGED, { detail: key }));
      inFlight.current = false;
      if (mounted.current) setBusy(false);
    }
  }
  async function send(path: string, payload: Record<string, unknown>, label: string, method: "POST" | "PUT" = "POST") {
    if (!allowedPath.test(path)) { setError("Dieser Vorgang ist nicht freigegeben."); return false; }
    if (current.current) { setError("Zuerst den bereits ausstehenden Vorgang prüfen."); return false; }
    return execute({ path, payload: { ...payload, request_key: payload.request_key ?? newRequestId() }, label, ...(method === "PUT" ? { method } : {}) }, false);
  }
  return { pending, busy, ready, blocked, error, clearError: () => setError(""), send, retry: () => current.current ? execute(current.current, true) : Promise.resolve(false) };
}
