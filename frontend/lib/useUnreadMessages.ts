"use client";

import { useCallback, useSyncExternalStore } from "react";
import { auth } from "@/lib/auth";
import { workerMessagesApi, hrMessagesApi } from "@/lib/api";

/**
 * Returns the number of unread message threads for the current user.
 * For workers: counts threads with unread_worker > 0
 * For recruiters/HR: counts threads with unread_hr > 0
 */
type Role = "worker" | "recruiter";
type Listener = (count: number) => void;
type MessageCache = {
  count: number;
  listeners: Set<Listener>;
  intervalId: ReturnType<typeof setInterval> | null;
  request: Promise<void> | null;
};

const caches = new Map<Role, MessageCache>();

function getCache(role: Role): MessageCache {
  const existing = caches.get(role);
  if (existing) return existing;
  const created: MessageCache = { count: 0, listeners: new Set(), intervalId: null, request: null };
  caches.set(role, created);
  return created;
}

function startPolling(role: Role, cache: MessageCache): void {
  if (cache.intervalId) return;

  const fetchCount = async (): Promise<void> => {
    if (cache.request) return cache.request;
    const token = auth.getAccess();
    if (!token || (role === "recruiter" && !auth.getUser()?.tenant_id)) return;

    cache.request = (async () => {
      try {
        const count = role === "worker"
          ? (await workerMessagesApi.list(token)).filter((t) => t.unread_worker > 0).length
          : (await hrMessagesApi.list(token, { unread_only: true })).length;
        cache.count = count;
        cache.listeners.forEach((listener) => listener(count));
      } catch {
        // The shared API request handles expired sessions and redirects.
      } finally {
        cache.request = null;
      }
    })();
    return cache.request;
  };

  void fetchCount();
  cache.intervalId = setInterval(() => void fetchCount(), 30_000);
}

export function useUnreadMessages(role: Role | null): number {
  const subscribe = useCallback((onChange: () => void) => {
    if (!role) return () => {};
    const cache = getCache(role);
    cache.listeners.add(onChange);
    startPolling(role, cache);
    return () => {
      cache.listeners.delete(onChange);
      if (cache.listeners.size === 0 && cache.intervalId) {
        clearInterval(cache.intervalId);
        cache.intervalId = null;
        cache.count = 0;
      }
    };
  }, [role]);
  const snapshot = useCallback(() => role ? getCache(role).count : 0, [role]);
  return useSyncExternalStore(subscribe, snapshot, () => 0);
}
