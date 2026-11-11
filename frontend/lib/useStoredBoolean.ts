"use client";

import { useCallback, useSyncExternalStore } from "react";

const LOCAL_CHANGE = "palmscout-preference-change";

function subscribe(listener: () => void) {
  window.addEventListener("storage", listener);
  window.addEventListener(LOCAL_CHANGE, listener);
  return () => {
    window.removeEventListener("storage", listener);
    window.removeEventListener(LOCAL_CHANGE, listener);
  };
}

/** Read a browser preference with a stable server snapshot and cross-tab updates. */
export function useStoredBoolean(key: string) {
  const snapshot = useCallback(() => {
    try { return localStorage.getItem(key) === "true"; } catch { return false; }
  }, [key]);
  const value = useSyncExternalStore(subscribe, snapshot, () => false);
  const setValue = useCallback((next: boolean) => {
    try { localStorage.setItem(key, String(next)); } catch { return; }
    window.dispatchEvent(new Event(LOCAL_CHANGE));
  }, [key]);
  return [value, setValue] as const;
}
