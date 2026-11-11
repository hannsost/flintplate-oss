"use client";
import { useEffect, useState } from "react";
import { auth } from "./auth";
import { AUTH_CHANGED_EVENT, ORDER_DRAFT_CHANGED_EVENT, ORDER_DRAFT_PREFIX, orderDraftScope } from "./flintplate-drafts";

export interface PendingRound { visitId: string }
/** Only this authenticated principal's round endpoints in this venue are visible. */
export function pendingRounds(venueId: string): PendingRound[] {
  const results: PendingRound[] = [];
  for (let index = 0; index < localStorage.length; index++) {
    const key = localStorage.key(index);
    if (!key?.startsWith(ORDER_DRAFT_PREFIX) || !key.includes(":round:")) continue;
    try {
      const value: unknown = JSON.parse(localStorage.getItem(key) ?? "null");
      if (!value || typeof value !== "object" || !("visitId" in value) || typeof value.visitId !== "string" || !("uncertain" in value) || value.uncertain !== true || !("pending" in value) || !value.pending) continue;
      const scope = orderDraftScope(auth.getUser(), `/gastro/venues/${venueId}/service-visits/${value.visitId}/rounds`);
      if (scope && key === `${scope}:round:${encodeURIComponent(value.visitId)}`) results.push({ visitId: value.visitId });
    } catch { /* The owning composer reports malformed storage without sending. */ }
  }
  return results;
}
export function usePendingRounds(venueId: string) {
  const [values, setValues] = useState<PendingRound[]>([]);
  useEffect(() => {
    const read = () => { try { setValues(pendingRounds(venueId)); } catch { setValues([]); } };
    read(); window.addEventListener("storage", read); window.addEventListener(AUTH_CHANGED_EVENT, read); window.addEventListener(ORDER_DRAFT_CHANGED_EVENT, read);
    return () => { window.removeEventListener("storage", read); window.removeEventListener(AUTH_CHANGED_EVENT, read); window.removeEventListener(ORDER_DRAFT_CHANGED_EVENT, read); };
  }, [venueId]);
  return values;
}
