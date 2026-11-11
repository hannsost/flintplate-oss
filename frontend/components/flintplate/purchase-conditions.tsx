"use client";

import { useState } from "react";
import { inputCents, type ProductConditions } from "@/lib/flintplate-purchasing";
import { Field } from "./shared";

export function readProductConditions(form: FormData): ProductConditions {
  const buy = Number(form.get("rebate_buy") || 0);
  const free = Number(form.get("rebate_free") || 0);
  if (Boolean(buy) !== Boolean(free)) throw new Error("Naturalrabatt benötigt bezahlte und kostenlose Gebinde gemeinsam.");
  const count = Number(form.get("tier_count") || 0);
  return {
    schema_version: 1, minimum_paid_packs: Number(form.get("minimum_packs") || 1),
    order_multiple: Number(form.get("order_multiple") || 1), tier_mode: "all_units",
    tiers: Array.from({ length: count }, (_, index) => ({ minimum_paid_packs: Number(form.get(`tier_min_${index}`)), pack_price_cents: inputCents(String(form.get(`tier_price_${index}`) || "0")) })),
    natural_rebate: buy && free ? { buy_packs: buy, free_packs: free } : null,
  };
}

export function ProductConditionFields({ initial }: { initial?: ProductConditions }) {
  const [tiers, setTiers] = useState(() => (initial?.tiers ?? []).map((row, index) => ({ ...row, key: index })));
  return <div className="fp-form-box">
    <h3>Mengen und Preisstaffeln</h3>
    <div className="fp-two"><Field label="Mindestzahl bezahlter Gebinde"><input name="minimum_packs" type="number" min="1" max="1000000" step="1" defaultValue={initial?.minimum_paid_packs ?? 1} required /></Field><Field label="Bestellen im Vielfachen von"><input name="order_multiple" type="number" min="1" max="1000000" step="1" defaultValue={initial?.order_multiple ?? 1} required /></Field></div>
    <p className="fp-description">Eine erreichte Preisstaffel gilt für alle bezahlten Gebinde dieser Bestellposition. Staffelgrenzen aufsteigend erfassen.</p>
    <input name="tier_count" type="hidden" value={tiers.length} />
    {tiers.map((tier, index) => <div key={tier.key} className="fp-form-box"><div className="fp-two"><Field label={`Staffel ${index + 1}: ab bezahlten Gebinden`}><input name={`tier_min_${index}`} type="number" min="1" max="1000000" step="1" value={tier.minimum_paid_packs} onChange={event => setTiers(rows => rows.map((row, at) => at === index ? { ...row, minimum_paid_packs: Number(event.target.value) } : row))} required /></Field><Field label={`Staffel ${index + 1}: Nettopreis je Gebinde in €`}><input name={`tier_price_${index}`} type="number" min="0" max="1000000" step="0.01" defaultValue={tier.pack_price_cents / 100} required /></Field></div><button type="button" className="fp-button" onClick={() => setTiers(rows => rows.filter((_, at) => at !== index))}>Staffel {index + 1} entfernen</button></div>)}
    <button type="button" className="fp-button" disabled={tiers.length >= 30} onClick={() => setTiers(rows => [...rows, { key: Math.max(-1, ...rows.map(row => row.key)) + 1, minimum_paid_packs: (rows.at(-1)?.minimum_paid_packs ?? 0) + 1, pack_price_cents: rows.at(-1)?.pack_price_cents ?? 0 }])}>Preisstaffel ergänzen</button>
    <h3>Naturalrabatt desselben Lieferartikels</h3>
    <div className="fp-two"><Field label="Je bezahlten Gebinden"><input name="rebate_buy" type="number" min="0" max="1000000" step="1" defaultValue={initial?.natural_rebate?.buy_packs ?? 0} /></Field><Field label="Zusätzliche Gratisgebinde"><input name="rebate_free" type="number" min="0" max="1000000" step="1" defaultValue={initial?.natural_rebate?.free_packs ?? 0} /></Field></div>
    <p className="fp-description">Beide Werte 0 bedeutet keinen Naturalrabatt. Gratisware erhöht den Bestand, nicht die abrechenbare Menge.</p>
  </div>;
}
