"use client";
import { useEffect, useState } from "react";
import { auth } from "@/lib/auth";
import { AUTH_CHANGED_EVENT } from "@/lib/flintplate-drafts";
import { venueApi, type Order } from "@/lib/flintplate";
import type { OrderServiceContext, TablePresence } from "@/lib/flintplate-visits";

const principal = () => { const user = auth.getUser(); return JSON.stringify([user?.tenant_id, user?.sub]); };
export function useOrderServiceContexts(venueId: string, orders: Order[]) {
  const [contexts, setContexts] = useState<Record<string, OrderServiceContext>>({});
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true; const scope = principal();
    const clear = () => { if (scope !== principal()) { active = false; setContexts({}); } };
    window.addEventListener(AUTH_CHANGED_EVENT, clear); window.addEventListener("storage", clear);
    async function read() {
      const values: OrderServiceContext[] = [];
      for (let offset = 0; offset < orders.length; offset += 100) {
        const query = new URLSearchParams(); orders.slice(offset, offset + 100).forEach(order => query.append("order_id", order.id));
        values.push(...await venueApi<OrderServiceContext[]>(venueId, `/order-service-contexts?${query}`));
        if (!active || scope !== principal()) return;
      }
      if (active && scope === principal()) { setContexts(Object.fromEntries(values.map(value => [value.order_id, value]))); setError(""); }
    }
    void read().catch(() => { if (active && scope === principal()) setError("Aktuelle Gäste- und Ortszuordnung konnte nicht geladen werden. Die Bonorte sind ursprüngliche Angaben."); });
    return () => { active = false; window.removeEventListener(AUTH_CHANGED_EVENT, clear); window.removeEventListener("storage", clear); };
  }, [venueId, orders]);
  return { contexts, error };
}

export function useServicePresence(venueId: string, revision: unknown) {
  const [presence, setPresence] = useState<TablePresence[]>([]);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true; const scope = principal();
    const clear = () => { if (scope !== principal()) { active = false; setPresence([]); } };
    window.addEventListener(AUTH_CHANGED_EVENT, clear); window.addEventListener("storage", clear);
    void venueApi<TablePresence[]>(venueId, "/service-presence").then(values => { if (active && scope === principal()) { setPresence(values); setError(""); } }).catch(() => { if (active && scope === principal()) setError("Gastanwesenheit konnte nicht aktualisiert werden. Bitte vor einer Neubelegung prüfen."); });
    return () => { active = false; window.removeEventListener(AUTH_CHANGED_EVENT, clear); window.removeEventListener("storage", clear); };
  }, [venueId, revision]);
  return { presence, error };
}
