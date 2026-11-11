"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { auth } from "@/lib/auth";
import { notificationsApi, type NotificationRead } from "@/lib/api";
import { wsClient, type WsEvent } from "@/lib/websocket";

export function NotificationBell() {
  const [notifications, setNotifications] = useState<NotificationRead[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Load on mount and subscribe to WS events
  useEffect(() => {
    const token = auth.getAccess();
    if (!token) return;

    // Initial fetch
    notificationsApi.list(token).then((res) => {
      setNotifications(res.notifications);
      setUnread(res.unread_count);
    }).catch(() => {});

    // Connect WS and listen for new notifications
    wsClient.connect(token);
    const off = wsClient.on("notification.new", (event: WsEvent) => {
      const n = event.payload as unknown as NotificationRead;
      setNotifications((prev) => [n, ...prev]);
      setUnread((c) => c + 1);
    });

    return () => {
      off();
    };
  }, []);

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  async function handleOpen() {
    setOpen((v) => !v);
    if (!open && unread > 0) {
      const token = auth.getAccess();
      if (!token) return;
      await notificationsApi.readAll(token).catch(() => {});
      setUnread(0);
      setNotifications((prev) => prev.map((n) => ({ ...n, read_at: n.read_at ?? new Date().toISOString() })));
    }
  }

  return (
    <div className="relative" ref={ref} onKeyDown={event => { if (event.key === "Escape") setOpen(false); }}>
      <button
        onClick={handleOpen}
        className="relative flex h-8 w-8 items-center justify-center rounded-lg border border-gray-200 text-gray-600 hover:border-gray-300 hover:text-gray-900 transition-colors"
        aria-label="Benachrichtigungen"
        aria-expanded={open}
        onKeyDown={event => { if (event.key === "Escape") setOpen(false); }}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {unread > 0 && (
          <span className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-blue-600 text-[10px] font-bold text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="fixed inset-x-4 top-28 z-50 rounded-xl sm:absolute sm:inset-x-auto sm:right-0 sm:top-10 sm:w-80 border border-gray-200 bg-white shadow-lg">
          <div className="border-b border-gray-100 px-4 py-2.5">
            <p className="text-sm font-medium text-gray-900">Benachrichtigungen</p>
          </div>

          <ul className="max-h-96 overflow-y-auto divide-y divide-gray-50">
            {notifications.length === 0 && (
              <li className="px-4 py-8 text-center text-sm text-gray-400">
                Keine Benachrichtigungen
              </li>
            )}
            {notifications.map((n) => (
              <li
                key={n.id}
                className={`px-4 py-3 ${!n.read_at ? "bg-blue-50/50" : ""}`}
              >
                <p className="text-sm font-medium text-gray-900 leading-snug">{n.title}</p>
                <p className="mt-0.5 text-xs text-gray-500 leading-snug">{n.body}</p>
                {typeof n.meta?.href === "string" && ["/offers", "/dashboard/offers", "/dashboard/onboarding"].includes(n.meta.href) && <Link href={n.meta.href} onClick={() => setOpen(false)} className="mt-2 inline-flex min-h-11 items-center text-sm font-medium text-blue-700">Vorgang öffnen</Link>}
                <p className="mt-1 text-[11px] text-gray-400">
                  {new Date(n.created_at).toLocaleDateString("de-DE", {
                    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
                  })}
                </p>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
