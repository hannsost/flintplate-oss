import { acceptance, expect } from './flintplate-acceptance-runner.mjs';

const t = await acceptance('flintplate-guest-payments-acceptance');
const { page, nav, modal, write, report } = t;
const composer = () => page.locator('[data-round="true"]');
const chips = () => page.getByLabel('Gäste dieser Runde', { exact: true });
const pay = () => page.getByRole('button', { name: /Bargeld erhalten$/ });
const ticket = number => page.locator('.fp-kitchen-ticket').filter({ hasText: number });
const preview = () => page.getByLabel('Zahlungsvorschau', { exact: true });
const parts = () => page.getByLabel('Gespeicherte Zahleranteile', { exact: true });
const part = ordinal => parts().getByRole('button', { name: new RegExp(`^Zahler ${ordinal}(?![0-9])`) });

async function guestOrders() {
  await nav('Bestellungen');
  await page.getByRole('button', { name: 'Gäste & Runden', exact: true }).click();
}
async function serve(child, item) {
  await nav('Küche & Bar');
  for (const state of ['Starten', 'Fertig', 'Servieren']) {
    await write(() => ticket(child.number).getByRole('button', { name: `${item}: ${state}`, exact: true }).click(), '/status', 200);
  }
}
async function cashFor(visitId) {
  await nav('Kasse');
  await page.getByRole('button', { name: 'Gäste & aufteilen', exact: true }).click();
  const selected = page.getByLabel('Besuch kassieren', { exact: true });
  await expect(selected).toBeEnabled();
  await selected.selectOption(visitId);
  await expect(page.getByLabel('Eigene offene Schichtkasse', { exact: true })).toBeEnabled();
}
let failure;
try {
  await t.login(); await nav('Kasse');
  await page.getByRole('button', { name: 'Einzelbon & Schichtkasse', exact: true }).click();
  await page.getByLabel('Neue Bargeldkasse', { exact: true }).fill(`Gästeprüfung ${Date.now().toString(36)}`);
  const register = await write(() => page.getByRole('button', { name: 'Kasse anlegen', exact: true }).click(), '/cash/registers');
  await page.getByLabel('Bargeldkasse', { exact: true }).selectOption(register.id);
  const operator = page.getByLabel('Verantwortliche Bedienung', { exact: true });
  await operator.selectOption(await operator.locator('option').filter({ hasText: 'Test Leitung' }).getAttribute('value'));
  await page.getByLabel('Gezählter Anfangsbestand in €', { exact: true }).fill('50');
  const session = await write(() => page.getByRole('button', { name: 'Schichtkasse öffnen', exact: true }).click(), '/cash/sessions');

  await guestOrders();
  await page.getByRole('button', { name: 'Neuer Besuch', exact: true }).click();
  await modal().getByLabel('Gäste', { exact: true }).fill('2');
  await modal().getByLabel('Gruppenname (optional)', { exact: true }).fill('Getrennt und gemeinsam');
  const visit = await write(() => modal().getByRole('button', { name: 'Besuch eröffnen', exact: true }).click(), '/service-visits');
  await expect(modal()).toHaveCount(0);
  for (const [guest, item] of [['Gast 1', 'Testgericht'], ['Gast 2', 'Testgericht'], ['Gemeinsam', 'Gemeinsame Flasche']]) {
    await chips().getByRole('button', { name: guest, exact: true }).click();
    await composer().getByRole('button', { name: `${item} hinzufügen`, exact: true }).click();
  }
  const round = await write(() => composer().getByRole('button', { name: 'Runde senden', exact: true }).click(), '/rounds');
  const a = round.children.find(child => child.label_snapshot === 'Gast 1');
  const b = round.children.find(child => child.label_snapshot === 'Gast 2');
  const shared = round.children.find(child => child.label_snapshot === 'Gemeinsam');
  expect(round.children).toHaveLength(3);
  await serve(a, 'Testgericht');
  await cashFor(visit.id);
  await expect(preview()).toContainText('noch nicht vollständig serviert');
  await expect(pay()).toBeDisabled();
  await page.getByRole('button', { name: 'Nach Gästen', exact: true }).click();
  await page.locator('.fp-pay-guests').getByRole('button', { name: /^Gast 1\b/ }).click();
  await page.getByLabel('Zusätzliches Trinkgeld in €', { exact: true }).fill('1,25');
  await page.getByLabel('Gegeben in € (optional)', { exact: true }).fill('20');
  await expect(pay()).toBeEnabled(); await expect(preview()).toContainText('11,25');
  await t.shot('gast-einzeln-zahlbar-waehrend-andere-kochen');
  const payloads = await t.loseFirstAnswer('**/api/gastro/venues/*/payment-groups/cash', true);
  await write(() => pay().click(), '/cash', 503);
  await page.reload(); await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' }); await nav('Kasse');
  await expect(page.getByRole('button', { name: 'Zahlungsvorgang erneut prüfen', exact: true })).toBeVisible();
  await write(() => page.getByRole('button', { name: 'Zahlungsvorgang erneut prüfen', exact: true }).click(), '/cash', 409);
  const first = await write(() => page.getByRole('button', { name: 'Zahlungsvorgang erneut prüfen', exact: true }).click(), '/cash');
  expect(payloads).toHaveLength(3); expect(payloads[1]).toEqual(payloads[0]); expect(payloads[2]).toEqual(payloads[0]);
  expect(first.receipt_amount_cents).toBe(1000); expect(first.new_tip_cents).toBe(125); expect(first.change_cents).toBe(875);
  expect(first.entries).toHaveLength(1); expect(first.entries[0].order_id).toBe(a.order_id);
  expect(first.entries[0].received_cents).toBeNull(); expect(first.entries[0].change_cents).toBeNull();
  report.checks.push('Nur servierter GastA wird kassiert, B und Shared bleiben offen. Eigenes125-Cent-Trinkgeld, einmal20€ gegeben/8,75€ Rückgeld. Commit503→Reload→409→Replay bestätigt exakt eine Gruppe.');

  await serve(b, 'Testgericht'); await serve(shared, 'Gemeinsame Flasche');
  await cashFor(visit.id);
  await page.getByRole('button', { name: 'Positionen auswählen', exact: true }).click();
  await page.getByRole('button', { name: 'Gemeinsame Flasche für Gemeinsam auswählen', exact: true }).click();
  await page.getByRole('button', { name: 'Auswahl gleichmäßig teilen', exact: true }).click();
  await page.getByRole('button', { name: 'Ein Zahler mehr', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Gleichaufteilung speichern', exact: true })).toBeEnabled();
  const plan = await write(() => page.getByRole('button', { name: 'Gleichaufteilung speichern', exact: true }).click(), '/equal-split-plans');
  expect(plan.total_cents).toBe(1001); expect(plan.parts.map(value => value.target_cents)).toEqual([334, 334, 333]);
  await expect(part(1)).toHaveAttribute('aria-pressed', 'true');
  await part(1).click(); await part(3).click();
  await expect(pay()).toBeEnabled();
  const third = await write(() => pay().click(), '/cash');
  expect(third.receipt_amount_cents).toBe(333); expect(third.new_tip_cents).toBe(0);
  expect(third.allocations).toHaveLength(1); expect(third.allocations[0].order_id).toBe(shared.order_id);
  // A successful HTTP response precedes the required authoritative reload.
  // This is the normal reload journey; lost-response recovery is tested above.
  await expect(page.getByLabel('Besuch kassieren', { exact: true })).toBeEnabled();
  await page.reload(); await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await cashFor(visit.id);
  await expect(parts()).toBeVisible(); await expect(part(3)).toBeDisabled();
  await expect(part(1)).toContainText('3,34'); await expect(part(2)).toContainText('3,34');
  await t.shot('gleichteilung-mit-festen-centanteilen-nach-reload');
  await expect(pay()).toBeEnabled(); const next = await write(() => pay().click(), '/cash');
  expect(next.receipt_amount_cents).toBe(334);
  await page.getByRole('button', { name: 'Nächster Zahler', exact: true }).first().click();
  await expect(part(2)).toHaveAttribute('aria-pressed', 'true');
  await expect(pay()).toBeEnabled(); const last = await write(() => pay().click(), '/cash');
  expect(last.receipt_amount_cents).toBe(334);
  expect(third.receipt_amount_cents + next.receipt_amount_cents + last.receipt_amount_cents).toBe(1001);
  expect(new Set([...third.allocations, ...next.allocations, ...last.allocations].map(row => `${row.order_id}:${row.line_id}:${row.unit}`)).size).toBe(1);
  report.checks.push('Eine Flasche bleibt eine originale Unit. Dauerhafter1001-Cent-Plan334/334/333, letzter Zahler zuerst, Reload und „Nächster Zahler“ erhalten die festen Restanteile; neues Trinkgeld wird nicht übernommen.');

  await page.getByRole('button', { name: 'Alles zusammen', exact: true }).click();
  await expect(pay()).toBeEnabled(); const remainder = await write(() => pay().click(), '/cash');
  expect(remainder.receipt_amount_cents).toBe(1000);
  expect(remainder.entries).toHaveLength(1); expect(remainder.entries[0].order_id).toBe(b.order_id);
  await expect(page.locator('.fp-payment-totals')).toContainText('0,00');
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 740 });
    await page.getByRole('button', { name: 'Nach Gästen', exact: true }).click();
    await t.shot(`getrennt-bezahlt-mobile-${width}`);
  }
  report.checks.push('Abschließende Auswahl kassiert ausschließlich Bs restlichen1000-Cent-Bon. Besuch offen0,00€, historische Quellen bleiben vorhanden. Desktop und390/320px mit Axe-/Overflowprüfung.');

  await page.setViewportSize({ width: 1440, height: 1050 });
  async function extraVisit(label, guest, item) {
    await guestOrders();
    await page.getByRole('button', { name: 'Neuer Besuch', exact: true }).click();
    await modal().getByLabel('Gäste', { exact: true }).fill('1');
    await modal().getByLabel('Gruppenname (optional)', { exact: true }).fill(label);
    const extra = await write(() => modal().getByRole('button', { name: 'Besuch eröffnen', exact: true }).click(), '/service-visits');
    await expect(modal()).toHaveCount(0);
    await chips().getByRole('button', { name: guest, exact: true }).click();
    await composer().getByRole('button', { name: `${item} hinzufügen`, exact: true }).click();
    const sent = await write(() => composer().getByRole('button', { name: 'Runde senden', exact: true }).click(), '/rounds');
    await serve(sent.children[0], item);
    return { visit: extra, child: sent.children[0] };
  }
  const bottleVisit = await extraVisit('Gemeinsame Runde', 'Gemeinsam', 'Gemeinsame Flasche');
  const laterVisit = await extraVisit('Späterer Gast', 'Gast 1', 'Testgericht');
  await cashFor(bottleVisit.visit.id);
  await page.getByRole('button', { name: 'Positionen auswählen', exact: true }).click();
  await page.getByRole('button', { name: 'Gemeinsame Flasche für Gemeinsam auswählen', exact: true }).click();
  await page.locator('.fp-payment-fraction summary').click();
  await page.getByRole('button', { name: 'Hälfte des offenen Betrags', exact: true }).click();
  await expect(pay()).toBeEnabled();
  const half = await write(() => pay().click(), '/cash');
  expect(half.receipt_amount_cents).toBe(501);
  expect(half.allocations).toHaveLength(1);

  await page.getByRole('button', { name: 'Nach Gästen', exact: true }).click();
  await page.getByRole('button', { name: `Gemeinsam aus ${bottleVisit.visit.label} · ${bottleVisit.visit.number} auswählen`, exact: true }).click();
  await page.getByRole('button', { name: 'Gäste aus anderem Besuch hinzufügen', exact: true }).click();
  await modal().getByLabel('Zusätzlicher Besuch', { exact: true }).selectOption(laterVisit.visit.id);
  await modal().getByRole('button', { name: 'Gäste dieses Besuchs anzeigen', exact: true }).click();
  await expect(modal()).toHaveCount(0);
  await page.getByRole('button', { name: `Gast 1 aus ${laterVisit.visit.label} · ${laterVisit.visit.number} auswählen`, exact: true }).click();
  await expect(pay()).toBeEnabled();
  await expect(preview()).toContainText('15,00');
  await t.shot('ein-zahler-fuer-getrennte-besuche-und-flaschenrest');
  const combined = await write(() => pay().click(), '/cash');
  expect(combined.receipt_amount_cents).toBe(1500);
  expect(new Set(combined.entries.map(entry => entry.order_id))).toEqual(new Set([bottleVisit.child.order_id, laterVisit.child.order_id]));
  const bottleRest = combined.allocations.filter(row => row.order_id === bottleVisit.child.order_id);
  expect(bottleRest).toHaveLength(1);
  expect(bottleRest[0].amount_cents).toBe(500);
  expect(bottleRest[0].line_id).toBe(half.allocations[0].line_id);
  expect(bottleRest[0].unit).toBe(half.allocations[0].unit);
  expect(bottleRest[0].tax_cents + half.allocations[0].tax_cents).toBe(bottleVisit.child.order.lines[0].tax_cents);
  report.checks.push('Direkte Hälfte einer1001-Cent-Flasche kassiert501Cent. Ein Zahler übernimmt anschließend ausdrücklich500Cent Rest und1000Cent eines unabhängigen Besuchs; zwei originale Bons, eine Zahlungsgruppe, Steuer und physische Unit unverändert.');

  const revisionVisit = await extraVisit('Restaufteilung prüfen', 'Gast 1', 'Testgericht');
  await cashFor(revisionVisit.visit.id);
  await page.getByRole('button', { name: 'Gleichmäßig teilen', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Gleichaufteilung speichern', exact: true })).toBeEnabled();
  const originalPlan = await write(() => page.getByRole('button', { name: 'Gleichaufteilung speichern', exact: true }).click(), '/equal-split-plans');
  expect(originalPlan.parts.map(value => value.target_cents)).toEqual([500, 500]);
  await page.getByRole('button', { name: 'Einzelbon & Schichtkasse', exact: true }).click();
  await page.getByLabel('Bon kassieren oder Zahlung ansehen', { exact: true }).selectOption(revisionVisit.child.order_id);
  await page.getByLabel('Offene Schichtkasse', { exact: true }).selectOption(session.id);
  await page.getByLabel('Teilbetrag in €', { exact: true }).fill('2');
  await write(() => page.getByRole('button', { name: 'Erhaltenes Bargeld bestätigen', exact: true }).click(), '/cash-payments', 200);
  await cashFor(revisionVisit.visit.id);
  await expect(parts()).toBeVisible();
  await expect(pay()).toBeDisabled();
  await page.getByRole('button', { name: 'Rest neu aufteilen', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Gleichaufteilung speichern', exact: true })).toBeDisabled();
  await page.getByLabel('Grund der neuen Restaufteilung', { exact: true }).fill('Nach separater Zahlung verbleibende Forderung neu vereinbart.');
  await expect(page.getByRole('button', { name: 'Gleichaufteilung speichern', exact: true })).toBeEnabled();
  const revised = await write(() => page.getByRole('button', { name: 'Gleichaufteilung speichern', exact: true }).click(), '/equal-split-plans');
  expect(revised.root_plan_id).toBe(originalPlan.id);
  expect(revised.revision).toBe(2);
  expect(revised.total_cents).toBe(800);
  expect(revised.parts.map(value => value.target_cents)).toEqual([400, 400]);
  await expect(page.getByLabel('Besuch kassieren', { exact: true })).toBeEnabled();
  await expect(page.getByRole('heading', { name: 'Gespeicherte Aufteilung · Stand 2', exact: true })).toBeVisible();
  await expect(part(1)).toContainText('4,00');
  await expect(part(2)).toContainText('4,00');
  await t.shot('explizite-restaufteilung-nach-separater-zahlung');
  report.checks.push('Separate200-Cent-Einzelbonzahlung sperrt den alten1000-Cent-Plan. Neue Restaufteilung verlangt eine Begründung und erzeugt Revision2 über800Cent mit400/400; alte Quellen bleiben erhalten.');
} catch (error) { failure = error; }
await t.finish(failure);
