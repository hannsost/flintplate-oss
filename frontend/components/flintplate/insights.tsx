"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, BarChart3, CalendarDays, CircleHelp, PackageSearch, RefreshCw, UtensilsCrossed } from "lucide-react";
import { auth } from "@/lib/auth";
import { message, money, venueApi, type Venue } from "@/lib/flintplate";
import { stockQuantity } from "@/lib/flintplate-inventory";
import type { PurchasePreparationIntent, SupplierSourceOption } from "@/lib/flintplate-purchase-preparation";
import { Empty, Field, Loading, Tag } from "./shared";

interface DishInsight {
  item_id: string;
  name: string;
  quantity: number;
  revenue_net_cents: number;
  refunded_net_cents: number;
  actual_consumption_cost_cents: number | null;
  recipe_cost_cents: number | null;
  contribution_cents: number | null;
  category: string;
}
interface Insights {
  window_days: number;
  cohort_start: string; cohort_through: string; as_of: string;
  unpaid_cancellation_net_cents?: number; revenue_before_refunds_net_cents: number; refunded_net_cents: number; legacy_paid_orders: number; unmatched_refund_entries: number;
  backtest: { evaluated_days: number; median_mae: number | null; prior_week_mae: number | null; from_date: string | null; through_date: string | null };
  reservation_history: { completed_reservations: number; no_shows: number; pending_past_reservations: number; no_show_rate: number | null };
  approved_work_through: string; approved_work_minutes: number; unvalued_work_minutes: number; labor_cost_cents: number | null;
  labor_known_cost_cents: number; labor_valued_minutes: number; labor_ambiguous_minutes: number; labor_rate_revision_ids: string[]; labor_source_fingerprint: string;
  stock_usage: { item_id: string; name: string; unit: string; consumed_quantity: string; waste_quantity: string; count_delta: string; production_input_quantity: string; known_consumption_cost_cents: number; unvalued_consumption_quantity: string; known_waste_cost_cents: number; unvalued_waste_quantity: string }[];
  paid_orders: number;
  revenue_net_cents: number;
  dishes: DishInsight[];
  purchasing: { item_id: string; name: string; unit: string; available_quantity: string; minimum_quantity: string; proposed_quantity: string; incoming_quantity_next7days: string; uncovered_after_incoming_quantity: string; earliest_confirmed_on: string | null; confirmation_ids: string[]; supplier_options: SupplierSourceOption[]; supplier_option_limit: number; reason: string }[];
  forecast: { date: string; expected_orders: number | null; lower_orders: number | null; upper_orders: number | null; comparable_days: number; reserved_guests: number }[];
  prepared_cancellations: number;
  method: string;
  limitations: string[];
}

export function InsightsPanel({ venue, onOpenInventory, onOpenRecipes, onOpenPurchasing }: { venue: Venue; onOpenInventory: () => void; onOpenRecipes: () => void; onOpenPurchasing: (intent?: PurchasePreparationIntent) => void }) {
  const [data, setData] = useState<Insights | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [filter, setFilter] = useState("all");
  const mounted = useRef(true), generation = useRef(0);
  const load = useCallback(async () => {
    setBusy(true);
    const request = ++generation.current, user = auth.getUser(), scope = JSON.stringify([user?.tenant_id, user?.sub]);
    const current = () => { const user = auth.getUser(); return mounted.current && request === generation.current && scope === JSON.stringify([user?.tenant_id, user?.sub]); };
    try {
      const result = await venueApi<Insights>(venue.id, "/insights");
      if (current()) { setData(result); setUpdated(new Date()); setError(""); }
    } catch (cause) { if (current()) setError(message(cause)); }
    finally { if (current()) setBusy(false); }
  }, [venue.id]);
  useEffect(() => { mounted.current = true; void load(); return () => { mounted.current = false; }; }, [load]);

  if (!data) return <section className="fp-panel">{error ? <p className="fp-notice error" role="alert">{error}<button className="fp-button" onClick={() => void load()}>Erneut laden</button></p> : <Loading />}</section>;
  const consumptionMissing = data.dishes.filter(dish => dish.actual_consumption_cost_cents === null).length;
  const decimal = (value: number) => new Intl.NumberFormat("de-DE", { maximumFractionDigits: 1 }).format(value);
  const unit = (value: string) => value === "piece" ? "Stück" : value;
  const missing = data.dishes.filter(dish => dish.recipe_cost_cents === null).length;
  const dishes = data.dishes.filter(dish => filter === "all" || (filter === "missing" && dish.recipe_cost_cents === null) || (filter === "negative" && dish.contribution_cents !== null && dish.contribution_cents < 0));
  const date = (value: string) => new Intl.DateTimeFormat("de-DE", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" }).format(new Date(`${value}T12:00:00Z`));

  return <section className="fp-stack">
    <div className="fp-section-head"><div><span className="fp-eyebrow">Deine letzten {data.window_days} Tage</span><h2>Was läuft. Was Aufmerksamkeit braucht.</h2><p>Verkäufe, Zutatenkosten und Lager aus den erfassten Betriebsdaten.</p></div><button className="fp-button" disabled={busy} onClick={() => void load()}><RefreshCw size={17} />{busy ? "Wird aktualisiert …" : "Aktualisieren"}</button></div>
    {error && <p className="fp-notice error" role="alert">{error} Die zuletzt geladenen Werte bleiben sichtbar.</p>}
    {(data.purchasing.length > 0 || missing > 0 || consumptionMissing > 0) && <section className="fp-panel"><div className="fp-section-head"><div><h2>Nächste Schritte</h2><p>{data.purchasing.length} Mindestbestände prüfen · {missing} Artikel ohne Rezeptkosten · {consumptionMissing} Artikel mit unvollständigen Verbrauchskosten</p></div><div className="fp-inline wrap">{data.purchasing.length > 0 && <button className="fp-button primary" onClick={() => onOpenPurchasing()}>Einkauf planen <ArrowRight size={16} /></button>}{missing > 0 && <button className="fp-button" onClick={onOpenRecipes}>Rezeptkosten pflegen</button>}{consumptionMissing > 0 && <button className="fp-button" onClick={onOpenInventory}>Lagerbelege prüfen</button>}</div></div></section>}
    <div className="fp-stats fp-insight-stats">
      <article className="fp-stat"><span>Produktumsatz nach Erstattungen<BarChart3 size={19} /></span><strong>{money(data.revenue_net_cents)}</strong><small>{money(data.revenue_before_refunds_net_cents)} netto vor · {money(data.refunded_net_cents)} zugeordnete Erstattungen</small>{(data.unpaid_cancellation_net_cents??0)>0&&<small>{money(data.unpaid_cancellation_net_cents??0)} unbezahlte Forderung durch Stornos erlassen, bereits im Umsatz berücksichtigt</small>}</article>
      <article className="fp-stat"><span>Bezahlte Bons<UtensilsCrossed size={19} /></span><strong>{data.paid_orders}</strong><small>Bonanlage {data.cohort_start.slice(0, 10)} bis {data.cohort_through.slice(0, 10)}</small></article>
      <article className="fp-stat"><span>Arbeitszeit unbewertet<CircleHelp size={19} /></span><strong>{decimal(data.unvalued_work_minutes / 60)} h</strong><small>{data.labor_cost_cents === null ? `Personalkosten unvollständig · ${money(data.labor_known_cost_cents)} belegt` : `${money(data.labor_cost_cents)} belegt`} · {decimal(data.approved_work_minutes / 60)} h genehmigt bis {data.approved_work_through.split("-").reverse().join(".")}</small></article>
      <article className="fp-stat"><span>Vorbereitet und storniert<PackageSearch size={19} /></span><strong>{data.prepared_cancellations}</strong><small>Erfasste Fälle zur Nachverfolgung</small></article>
    </div>
    {(data.legacy_paid_orders > 0 || data.unmatched_refund_entries > 0) && <p className="fp-notice">Daten prüfen: {data.legacy_paid_orders} ältere bezahlte Bons und {data.unmatched_refund_entries} nicht zuordenbare Erstattungsbuchungen. Die Umsatzbasis ist in den Datengrenzen beschrieben.</p>}
    <section className="fp-panel"><div className="fp-section-head"><div><h2>Beiträge aus der Karte</h2><p>Netto nach zugeordneten Erstattungen abzüglich kalkulierter Zutatenkosten. Verbrauchskosten bleiben bei Geldrückzahlungen bestehen.</p></div><button className="fp-text-button" onClick={onOpenRecipes}>Rezeptkosten pflegen <ArrowRight size={17} /></button></div>
      <Field label="Gerichte eingrenzen"><select value={filter} onChange={event => setFilter(event.target.value)}><option value="all">Alle verkauften Gerichte</option><option value="missing">Rezeptkosten fehlen</option><option value="negative">Negativer Beitrag</option></select></Field>
      {missing > 0 && <p className="fp-notice">Bei {missing} {missing === 1 ? "Artikel fehlen" : "Artikeln fehlen"} Rezeptkosten für mindestens eine verkaufte Position. Ihr Beitrag bleibt offen.</p>}
      {dishes.length ? <div className="fp-table-wrap"><table><caption className="fp-visually-hidden">Produktumsatz, kalkulierte Rezeptkosten und Beitrag je Gericht für {data.window_days} Tage</caption><thead><tr><th scope="col">Gericht</th><th scope="col">Bestellt (inkl. Stornos)</th><th scope="col">Netto-Umsatz</th><th scope="col">Rezeptkosten</th><th scope="col">Belegter Verbrauch</th><th scope="col">Kalkulierter Beitrag</th><th scope="col">Einordnung</th></tr></thead><tbody>{dishes.map(dish => <tr key={dish.item_id}><td><strong>{dish.name}</strong></td><td>{dish.quantity}</td><td>{money(dish.revenue_net_cents)}<small>{money(dish.refunded_net_cents)} erstattet</small></td><td>{dish.recipe_cost_cents === null ? <Tag tone="amber">Kosten fehlen</Tag> : money(dish.recipe_cost_cents)}</td><td>{dish.actual_consumption_cost_cents === null ? <Tag tone="amber">Belegkosten unvollständig</Tag> : money(dish.actual_consumption_cost_cents)}</td><td>{dish.contribution_cents === null ? "Noch offen" : <strong>{money(dish.contribution_cents)}</strong>}</td><td><Tag tone={dish.contribution_cents === null || dish.contribution_cents < 0 ? "amber" : "green"}>{dish.category}</Tag></td></tr>)}</tbody></table></div> : <Empty title={data.dishes.length ? "Keine Gerichte in dieser Auswahl" : "Die ersten Verkäufe machen den Anfang"}>{data.dishes.length ? "Wähle einen anderen Filter." : "Bestätigte Produktverkäufe erscheinen hier automatisch."}</Empty>}
      <p className="fp-description">Die Menge umfasst ursprünglich bestellte Portionen einschließlich späterer Stornos. Die Rezeptkalkulation und die Einordnung je Portion verwenden diese Originalmenge. Der ausgewiesene Gesamtbeitrag berücksichtigt Erlasse und tatsächliche Erstattungen im Umsatz. Belegter Lagerverbrauch bleibt separat sichtbar. Personal und weitere Betriebskosten sind im Beitrag noch nicht enthalten.</p>
    </section>
    <section className="fp-panel"><div className="fp-section-head"><div><span className="fp-eyebrow">Planung für die nächsten 7 Tage</span><h2>Ein Anhaltspunkt für die Woche</h2></div><CalendarDays size={23} /></div>
      <p className="fp-description">{data.method}</p>
      <div className="fp-forecast-grid">{data.forecast.map(day => <article className={`fp-forecast-day ${day.expected_orders === null ? "insufficient" : ""}`} key={day.date}><h3>{date(day.date)}</h3><strong>{day.expected_orders === null ? "–" : day.expected_orders}</strong><span>{day.expected_orders === null ? "Noch keine belastbare Basis" : "erwartete Bestellungen"}</span><small>{day.expected_orders === null ? `${day.comparable_days} von mindestens 4 Vergleichstagen` : `Bisher ${day.lower_orders}–${day.upper_orders} · ${day.comparable_days} Vergleichstage`}</small><p><b>{day.reserved_guests}</b> reservierte Gäste</p></article>)}</div>
      <p className="fp-description">Die Spanne zeigt beobachtete Vergleichstage. Reservierte Gäste stehen separat daneben und werden nicht in Bestellungen umgerechnet. Wetter, Öffnungszeiten und Veranstaltungen sind keine Prognosefaktoren.</p>
    </section>
    <details className="fp-panel"><summary>Prognose im Rücktest und Reservierungsverlauf</summary><p className="fp-description">Vergangene Tage werden nur mit den jeweils vorher verfügbaren Bestellungen vorhergesagt. Die mittlere absolute Abweichung wird in Bestellungen angegeben.</p><div className="fp-inline"><Tag>{data.backtest.evaluated_days} geprüfte Tage</Tag><Tag>Wochentagsmedian: {data.backtest.median_mae === null ? "Basis fehlt" : `${decimal(data.backtest.median_mae)} Bestellungen Abweichung`}</Tag><Tag>Vorwoche: {data.backtest.prior_week_mae === null ? "Basis fehlt" : `${decimal(data.backtest.prior_week_mae)} Bestellungen Abweichung`}</Tag></div>{data.backtest.from_date && data.backtest.through_date && <p>{date(data.backtest.from_date)}–{date(data.backtest.through_date)}</p>}<p className="fp-description">Geplante Reservierungen: {data.reservation_history.completed_reservations} erschienen · {data.reservation_history.no_shows} nicht erschienen · {data.reservation_history.pending_past_reservations} vergangene Vorgänge ungeklärt. Spontane Gäste und Warteliste sind ausgenommen.</p><p>Nicht erschienen: {data.reservation_history.no_show_rate === null ? "Noch keine geklärte Vergleichsbasis" : new Intl.NumberFormat("de-DE", { style: "percent", maximumFractionDigits: 1 }).format(data.reservation_history.no_show_rate)} der geklärten geplanten Reservierungen.</p></details>
    <details className="fp-panel"><summary>Personalkosten: belegte Anteile und offene Zuordnung</summary><p>{decimal(data.labor_valued_minutes / 60)} h bewertet · {decimal(data.unvalued_work_minutes / 60)} h unbewertet · davon {decimal(data.labor_ambiguous_minutes / 60)} h mehrdeutig zugeordnet.</p><p>{money(data.labor_known_cost_cents)} belegte kalkulatorische Kosten aus {data.labor_rate_revision_ids.length} festen Kostensatzrevisionen. {data.labor_cost_cents === null ? "Ein vollständiger Gesamtbetrag bleibt offen, bis die Lücken geklärt sind." : "Die erfasste Arbeitszeit ist vollständig bewertet."}</p><p className="fp-description">Genehmigte Arbeitszeiten bis {data.approved_work_through.split("-").reverse().join(".")}, Bruttostundenentgelt mit belegtem Arbeitgeberzuschlag. Die Bewertung ist keine Gehaltsabrechnung.</p></details>
    <details className="fp-panel"><summary>Eigenbestand: Verbrauch, Schwund und Beleglücken</summary><p className="fp-description">Bewertung aus belegten Bestellpreisen beim Verbrauch. Gratisware hat belegte Kosten von 0 €. Unbelegte Zugänge bleiben unbewertet. Rechnungskorrekturen, Fracht und Boni sind noch nicht eingerechnet.</p>{data.stock_usage.length ? <div className="fp-table-wrap"><table><thead><tr><th>Artikel</th><th>Verbrauch</th><th>Schwund</th><th>Inventurdifferenz</th><th>Produktionseinsatz</th></tr></thead><tbody>{data.stock_usage.map(row => <tr key={row.item_id}><td><strong>{row.name}</strong><small>{unit(row.unit)}</small></td><td>{stockQuantity(row.consumed_quantity)}<small>{money(row.known_consumption_cost_cents)} belegt</small><small>{stockQuantity(row.unvalued_consumption_quantity)} ohne Kostenbeleg</small></td><td>{stockQuantity(row.waste_quantity)}<small>{money(row.known_waste_cost_cents)} belegt</small><small>{stockQuantity(row.unvalued_waste_quantity)} ohne Kostenbeleg</small></td><td>{stockQuantity(row.count_delta)}</td><td>{stockQuantity(row.production_input_quantity)}<small>Separat, um fertige Portionen nicht doppelt zu zählen</small></td></tr>)}</tbody></table></div> : <Empty title="Noch keine Lagerverbräuche im Zeitraum">Belegte Verbrauchs- und Schwundbuchungen erscheinen hier.</Empty>}</details>
    <section className="fp-panel"><div className="fp-section-head"><div><h2>Mindestbestände nachfüllen</h2><p>Vorschläge anhand des verfügbaren Eigenbestands. Heutige Lücke und bestätigten Zulauf gemeinsam vor dem Einkauf prüfen.</p></div><div className="fp-inline wrap"><button className="fp-text-button" onClick={onOpenInventory}>Lager öffnen <ArrowRight size={17} /></button><button className="fp-button" onClick={() => onOpenPurchasing()}>Einkauf planen <ArrowRight size={17} /></button></div></div>
      {data.purchasing.length ? <div className="fp-stock-suggestions">{data.purchasing.map(item => <div key={item.item_id}><article className="fp-stock-suggestion"><div><strong>{item.name}</strong><small>Verfügbar {stockQuantity(item.available_quantity)} · Mindestbestand {stockQuantity(item.minimum_quantity)} {item.unit === "piece" ? "Stück" : item.unit}</small><p>{item.reason}</p><p>Zugesagt für die nächsten 7 Tage: {stockQuantity(item.incoming_quantity_next7days)} {unit(item.unit)}{item.earliest_confirmed_on ? ` · frühestens ${date(item.earliest_confirmed_on)}` : ""}</p><small>{item.confirmation_ids.length} belegte Zusagen · heute noch nicht verfügbar</small></div><span><b>+{stockQuantity(item.proposed_quantity)}</b><small>{unit(item.unit)} fehlen heute</small><strong>{stockQuantity(item.uncovered_after_incoming_quantity)} {unit(item.unit)}</strong><small>nach geplantem Zulauf noch ungedeckt</small></span></article>
        {Number(item.uncovered_after_incoming_quantity) > 0 && <details className="fp-form-box"><summary>Lieferanten vergleichen · {item.supplier_options.length} Optionen</summary><p className="fp-description">Bis zu {item.supplier_option_limit} erfasste Lieferartikel, alphabetisch nach Lieferant und Artikelnummer. Die Auswahl ist keine vollständige Marktübersicht. Konditionen werden vor dem Einkaufsentwurf erneut geprüft.</p>
          {item.supplier_options.length ? item.supplier_options.map(source => <article className="fp-form-box" key={source.product_id}><div className="fp-section-head"><div><h3>{source.supplier_name}</h3><p>{source.supplier_sku} · {source.pack_name} mit {stockQuantity(source.pack_quantity)} {unit(source.unit)}</p></div><Tag tone={source.blocking_reasons.length ? "amber" : "neutral"}>{source.net_cents === null ? "Nicht berechenbar" : `${money(source.net_cents)} netto`}</Tag></div>
            {source.packs !== null && <p><strong>{source.packs} bezahlte + {source.bonus_packs ?? 0} Gratisgebinde</strong> · {stockQuantity(source.ordered_quantity ?? "0")} {unit(source.unit)} insgesamt · {stockQuantity(source.overage_quantity ?? "0")} {unit(source.unit)} über Bedarf</p>}
            <p className="fp-description">{source.pack_price_cents === null ? "Gebindepreis ungeklärt" : `${money(source.pack_price_cents)} je bezahltem Gebinde`}{source.net_cents !== null && Number(source.ordered_quantity) > 0 ? ` · effektiv ${money(Math.round(source.net_cents / Number(source.ordered_quantity)))} je ${unit(source.unit)} einschließlich Gratisware` : ""} · Preisstand {source.price_version} ab {date(source.price_effective_on)}</p>
            <p>{source.earliest_delivery_on ? `Lieferannahme frühestens ${date(source.earliest_delivery_on)}` : "Liefertermin unbekannt"} · {source.minimum_order_net_cents === null ? "Mindestbestellwert unbekannt" : `Mindestbestellwert ${money(source.minimum_order_net_cents)} netto`}</p>
            {source.shortfall_to_minimum_net_cents !== null && source.shortfall_to_minimum_net_cents > 0 && <p>Zum Mindestbestellwert fehlen {money(source.shortfall_to_minimum_net_cents)}. Weitere Artikel können im Entwurf ergänzt werden.</p>}
            {source.blocking_reasons.length > 0 && <ul className="fp-description">{source.blocking_reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>}
            <button className="fp-button" disabled={busy || source.packs === null || source.packs <= 0} onClick={() => onOpenPurchasing({ item_name: item.name, source })}>Einkaufsentwurf vorbereiten <ArrowRight size={16} /></button>
          </article>) : <p>Für diesen Restbedarf ist kein Lieferartikel mit gültigem Preis erfasst.</p>}
          <p className="fp-description">Lieferannahmen sind keine belegten Lieferzusagen. Steuer kommt zum Nettowert hinzu.</p>
        </details>}
      </div>)}</div> : <Empty title="Kein Mindestbestand unterschritten">Vorschläge erscheinen, sobald verfügbarer Eigenbestand unter einem hinterlegten Mindestbestand liegt.</Empty>}
    </section>
    <details className="fp-panel"><summary>Datengrundlage und Grenzen</summary><p>Auswertungsstand: {new Date(data.as_of).toLocaleString("de-DE", { timeZone: venue.timezone })}. Erstattungen beziehen sich auf die bezahlten Bons aus dem angegebenen Anlagezeitraum.</p><ul>{data.limitations.map(limit => <li key={limit}>{limit}</li>)}</ul>{updated && <small>Zuletzt geladen: {updated.toLocaleString("de-DE", { timeZone: venue.timezone })}</small>}</details>
  </section>;
}
