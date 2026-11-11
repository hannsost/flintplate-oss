"use client";

import { useState } from "react";
import { ScanLine } from "lucide-react";
import { auth } from "@/lib/auth";
import { message, venueApi } from "@/lib/flintplate";
import { inventoryApi, type InventorySnapshot, type StockLot } from "@/lib/flintplate-inventory";
import { Empty, Loading, Modal, Tag } from "./shared";

type Provenance = {
  order_id: string;
  lots: StockLot[];
  operation_ids: string[];
  receipts: { receipt_id: string; purchase_order_id: string; supplier_id: string; operation_id: string }[];
  truncated: boolean;
  coverage: string;
};

export function OrderProvenanceButton({ venueId, orderId, number }: { venueId: string; orderId: string; number: string }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [trace, setTrace] = useState<Provenance | null>(null);
  const [stock, setStock] = useState<InventorySnapshot | null>(null);
  async function show() {
    setOpen(true); setLoading(true); setError(""); setTrace(null);
    const user = auth.getUser();
    try {
      const [nextTrace, nextStock] = await Promise.all([
        venueApi<Provenance>(venueId, `/orders/${orderId}/provenance`),
        inventoryApi<InventorySnapshot>(venueId, "/snapshot"),
      ]);
      const current = auth.getUser();
      if (current?.sub !== user?.sub || current?.tenant_id !== user?.tenant_id) return;
      setTrace(nextTrace); setStock(nextStock);
    } catch (cause) { setError(message(cause)); }
    finally { setLoading(false); }
  }
  return <>
    <button className="fp-button ghost" onClick={() => void show()} aria-label={`Zutatenherkunft für ${number}`}><ScanLine size={16} /> Zutatenherkunft</button>
    {open && <Modal title={`${number} · Zutatenherkunft`} onClose={() => setOpen(false)}>
      {loading && <Loading />}{error && <div role="alert" className="fp-notice error">{error}</div>}
      {trace && <>
        <p>{trace.coverage}</p>
        {trace.truncated && <div className="fp-notice error" role="alert">Die Herkunft umfasst mehr als 500 Chargen. Diese Ansicht ist unvollständig; bitte den Betrieb für einen vollständigen Abgleich hinzuziehen.</div>}
        {!trace.lots.length ? <Empty title="Keine Chargenbuchung vorhanden">Für diesen Bon ist noch kein Zutatenverbrauch erfasst. Unbekannte Herkunft bleibt offen.</Empty> : <div className="fp-stack">{trace.lots.map(lot => <article className="fp-panel" key={lot.id}>
          <div className="fp-section-head"><h3>{stock?.items.find(item => item.id === lot.item_id)?.name ?? "Lagerartikel"}</h3><Tag tone={lot.blocked ? "amber" : "neutral"}>{lot.blocked ? "Gesperrt" : "Erfasste Charge"}</Tag></div>
          <p>Charge {lot.code} · {stock?.owners.find(owner => owner.id === lot.owner_id)?.name ?? "Eigentümer hinterlegt"}</p>
          {lot.expires_on && <p>MHD: {new Intl.DateTimeFormat("de-DE", { timeZone: "UTC" }).format(new Date(`${lot.expires_on}T12:00:00Z`))}</p>}
        </article>)}</div>}
        {trace.receipts.length > 0 && <><h3>Zugehörige Wareneingänge</h3><ul>{trace.receipts.map(receipt => <li key={receipt.receipt_id}>Eingangsbeleg {receipt.receipt_id.slice(0, 8)} · Einkaufsauftrag {receipt.purchase_order_id.slice(0, 8)}</li>)}</ul></>}
        <p className="fp-muted">{trace.operation_ids.length} verknüpfte Lagerbuchungen. Rückrufe werden in Lager &amp; Waren ausgelöst.</p>
      </>}
    </Modal>}
  </>;
}
