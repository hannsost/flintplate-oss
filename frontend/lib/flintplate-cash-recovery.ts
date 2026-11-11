"use client";
import { useEffect, useState } from "react";
import { auth } from "./auth";
import { AUTH_CHANGED_EVENT } from "./flintplate-drafts";
export const CASH_RECOVERY_CHANGED = "flintplate-cash-pending-changed";
export type CashRecovery = { group: boolean; legacy: boolean; unavailable: boolean };
export type CashPanelView = "guests" | "single";
/** Completing recovery keeps its source visible until the operator changes tabs. */
export function cashViewForRecovery(current: CashPanelView, recovery: CashRecovery): CashPanelView {
  return recovery.group ? "guests" : recovery.legacy ? "single" : current;
}
export function cashRecovery(venueId: string) {
  const user = auth.getUser();
  if (!user?.sub) return { group: false, legacy: false, unavailable: false };
  try {
    return {
      group: !!localStorage.getItem(`flintplate:payment-group-pending:v1:${encodeURIComponent(JSON.stringify([user.tenant_id, user.sub, venueId]))}`),
      legacy: !!localStorage.getItem(`flintplate:cash-pending:v1:${encodeURIComponent(JSON.stringify([user.tenant_id, user.sub]))}:${venueId}`),
      unavailable: false,
    };
  } catch { return { group: false, legacy: false, unavailable: true }; }
}
export function useCashRecovery(venueId: string, onRead?: (value: CashRecovery) => void) {
  const [value, setValue] = useState({ group: false, legacy: false, unavailable: false });
  useEffect(() => {
    const read = () => { const next = cashRecovery(venueId); setValue(next); onRead?.(next); }; read();
    const events = ["storage", AUTH_CHANGED_EVENT, CASH_RECOVERY_CHANGED, "flintplate-pending-mutation-changed"];
    events.forEach(event => window.addEventListener(event, read));
    return () => events.forEach(event => window.removeEventListener(event, read));
  }, [venueId, onRead]);
  return value;
}
