import { chromium, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs/promises';
import { fulfillFromIsolatedApi, requestIsolatedApi } from './flintplate-browser-api.mjs';

// Requires the existing isolated acceptance process at schema >=076. Every
// mutation below uses visible UI controls; neither setup nor assertions write
// directly to an API, a database, localStorage or browser application state.
const socket = process.env.FLINTPLATE_BROWSER_SOCKET;
if (!socket) throw new Error('FLINTPLATE_BROWSER_SOCKET is required; demo writes are forbidden.');
const credentials = JSON.parse(await fs.readFile(process.env.FLINTPLATE_BROWSER_CREDENTIALS ?? new URL('../../backend/.local/browser-acceptance-access.json', import.meta.url), 'utf8'));
const resumeTag = process.env.FLINTPLATE_PARTNER_RESUME_TAG;
const output = `/tmp/hireos-browser-tests/flintplate-partners-reservations-acceptance${resumeTag ? '-continuation' : ''}`;
await fs.mkdir(output, { recursive: true });
const tag = resumeTag ?? Date.now().toString(36);
const names = { menu: `Partnerportion ${tag}`, partnerItem: `Kommissionsware ${tag}`, ownItem: `Reserveware ${tag}`, partner: `Prüfpartner ${tag}`, own: `Reservebetrieb ${tag}`, location: `Prüflager ${tag}`, contract: `Kommission ${tag}`, till: `Partnerkasse ${tag}`, loan: `Leihkisten ${tag}` };
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH ?? '/tmp/palmscout-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell', headless: true, args: ['--disable-gpu', '--disable-dev-shm-usage', '--no-sandbox'] });
const context = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 1440, height: 1050 }, timezoneId: 'Europe/Berlin' });
const page = await context.newPage();
page.setDefaultTimeout(45000);
const report = { isolated: true, checks: [], screenshots: [], errors: [], writes: [] };
page.on('pageerror', error => report.errors.push(error.message));
page.on('response', response => { if (response.url().includes('/api/') && response.request().method() === 'GET' && response.status() >= 400) report.errors.push(`${response.status()} GET ${new URL(response.url()).pathname}`); });
await context.route('**/*', async route => {
  const request = route.request(), url = new URL(request.url());
  if (url.origin !== 'http://localhost:3012' || !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) { report.errors.push(`Blocked unproxied request: ${request.method()} ${url.pathname}`); await route.abort('blockedbyclient'); }
  else await route.continue();
});
await context.route('**/api/**', route => fulfillFromIsolatedApi(route, socket));
const modal = () => page.getByRole('dialog');
const partnerCard = () => page.locator('section.fp-panel').filter({ has: page.getByRole('heading', { name: names.contract, exact: true }) });
const stockRow = name => page.getByRole('row').filter({ hasText: name });
const loanCard = () => page.locator('section.fp-panel').filter({ has: page.getByRole('heading', { name: names.loan, exact: true }) });
async function nav(name) { await page.getByRole('navigation', { name: 'Betriebsnavigation' }).getByRole('button', { name, exact: false }).click(); await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' }); }
async function write(click, suffix, expected = 201) {
  const [response] = await Promise.all([page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith(suffix)), click()]); const json = await response.json();
  report.writes.push({ path: new URL(response.url()).pathname, status: response.status() });
  console.log(JSON.stringify({ checkpoint: suffix, status: response.status() }));
  expect(response.status(), JSON.stringify(json)).toBe(expected);
  return json;
}
async function submit(label, suffix, expected = 201) { const result = await write(() => modal().getByRole('button', { name: label, exact: true }).click(), suffix, expected); if (expected < 300) await expect(modal()).toHaveCount(0); return result; }
async function screenshot(name) {
  await page.evaluate(async () => { await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => undefined))); });
  const axe = await new AxeBuilder({ page }).include('.fp').withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
  const path = `${output}/${name}.png`; await page.screenshot({ path, fullPage: page.viewportSize().width > 700 });
  report.screenshots.push({ path, viewport: page.viewportSize(), overflow, violations: axe.violations.map(item => ({ id: item.id, targets: item.nodes.map(node => node.target) })) });
  expect(overflow).toBe(false); expect(axe.violations).toEqual([]);
}
async function loseFirstAnswer(pattern) {
  const payloads = [];
  await page.route(pattern, async route => {
    if (route.request().method() !== 'POST') { await route.fallback(); return; }
    payloads.push(route.request().postDataJSON()); const response = await requestIsolatedApi(route.request(), socket);
    if (payloads.length === 1) { expect(response.status).toBe(201); await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Isolierte Prüfung: gebucht, erste Bestätigung gezielt verloren.' }) }); }
    else await route.fulfill(response);
  });
  return payloads;
}
async function receive(item, owner, location, lot, quantity, unit) {
  await page.getByRole('button', { name: 'Wareneingang', exact: true }).click();
  await modal().getByLabel('Lagerartikel', { exact: true }).selectOption(item.id);
  await modal().getByLabel('Eigentümer dieser Ware').selectOption(owner.id);
  await modal().getByLabel('Lagerort', { exact: true }).selectOption(location.id);
  await modal().getByLabel('Liefercharge').fill(lot);
  await modal().getByLabel(`Menge in ${unit}`, { exact: true }).fill(quantity);
  await modal().getByLabel('MHD', { exact: true }).fill(new Date(Date.now() + 14 * 86400000).toISOString().slice(0, 10));
  await modal().getByLabel('Lieferschein / Referenz').fill(`LS-${lot}`);
  return submit('Buchung bestätigen', '/receipts');
}
try {
  await page.goto('http://localhost:3012/anmelden?next=%2Fgastro');
  await page.getByLabel('E-Mail-Adresse').fill(credentials.manager); await page.getByLabel('Passwort', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click(); await page.waitForURL('**/gastro');
  await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });

  let menu, location, contract;
  const items = [], owners = [];
  if (resumeTag) {
    const [menuResponse, inventoryResponse, partnerResponse] = await Promise.all([
      page.waitForResponse(response => response.request().method() === 'GET' && new URL(response.url()).pathname.endsWith('/menu')),
      page.waitForResponse(response => response.request().method() === 'GET' && new URL(response.url()).pathname.endsWith('/inventory/snapshot')),
      page.waitForResponse(response => response.request().method() === 'GET' && new URL(response.url()).pathname.endsWith('/partners/snapshot')),
      nav('Partnerabrechnung'),
    ]);
    const drafts = await menuResponse.json(), stock = await inventoryResponse.json(), partners = await partnerResponse.json();
    menu = drafts.find(row => row.draft.name === names.menu);
    items.push(...[names.partnerItem, names.ownItem].map(name => stock.items.find(row => row.name === name)));
    owners.push(...[names.partner, names.own].map(name => stock.owners.find(row => row.name === name)));
    location = stock.locations.find(row => row.name === names.location);
    contract = partners.contracts.find(row => row.name === names.contract);
    expect([menu, location, contract, ...items, ...owners].every(Boolean)).toBe(true);
    report.checks.push('Definierte Fortsetzung nach erfolgreicher Einrichtung: vorhandenen Vertrag und die beiden Eingänge per UI-Leseantwort geladen.');
  } else {
  await nav('Karte & Preise'); await page.getByRole('button', { name: 'Artikel', exact: true }).click();
  await modal().getByLabel('Artikelnummer').fill(`PARTNER-${tag}`); await modal().getByLabel('Artikelname').fill(names.menu);
  await modal().getByLabel('Verkaufspreis in €', { exact: true }).fill('10'); await modal().getByLabel('Steuersatz in %', { exact: true }).fill('19');
  menu = await submit('Entwurf speichern', '/menu');
  await write(() => stockRow(names.menu).getByRole('button', { name: 'Veröffentlichen', exact: true }).click(), `/${menu.id}/publish`, 200);
  await nav('Lager & Waren'); await page.getByRole('button', { name: 'Artikel & Orte', exact: true }).click();
  for (const [sku, name, unit] of [[`PARTNER-${tag}`, names.partnerItem, 'piece'], [`HOLD-${tag}`, names.ownItem, 'kg']]) {
    await page.getByRole('button', { name: 'Artikel', exact: true }).click();
    await modal().getByLabel('Lagernummer').fill(sku); await modal().getByLabel('Artikelname').fill(name); await modal().getByLabel('Basiseinheit').selectOption(unit);
    await modal().getByLabel('MHD beim Wareneingang erforderlich').check(); items.push(await submit('Anlegen', '/items'));
  }
  for (const [name, kind] of [[names.partner, 'partner'], [names.own, 'own']]) {
    await page.getByRole('button', { name: 'Eigentümer', exact: true }).click();
    await modal().getByLabel('Name des Eigentümers').fill(name); await modal().getByLabel('Eigentum', { exact: true }).selectOption(kind); owners.push(await submit('Anlegen', '/owners'));
  }
  await page.getByRole('button', { name: 'Lagerort', exact: true }).click(); await modal().getByLabel('Name des Lagerorts').fill(names.location);
  location = await submit('Anlegen', '/locations');
  await receive(items[0], owners[0], location, `PARTNER-LOT-${tag}`, '100', 'Stück');
  await receive(items[1], owners[1], location, `HOLD-LOT-${tag}`, '10', 'kg');

  await nav('Partnerabrechnung'); await page.getByRole('button', { name: 'Vertrag anlegen', exact: true }).click();
  await modal().getByLabel('Vertragsname').fill(names.contract); await modal().getByLabel('Partner-Eigentümer', { exact: true }).selectOption(owners[0].id);
  await modal().getByLabel('Lagerartikel', { exact: true }).selectOption(items[0].id); await modal().getByLabel('Menüartikel für direkten Wiederverkauf').selectOption(menu.id);
  await modal().getByLabel('Partnerbetrag je Verkaufseinheit in Euro').fill('1'); await modal().getByLabel('Fester Monatsbetrag in Euro (negativ = Miete an Betrieb)').fill('5');
  await modal().getByLabel('Wer trägt Bruch und Verlust?').selectOption('venue'); await modal().getByLabel('Verlustwert je Lager-Basiseinheit in Euro').fill('2');
  await modal().getByLabel('Begründung', { exact: true }).fill('Isolierter Kommissionsvertrag'); contract = await submit('Speichern', '/contracts');
  await expect(partnerCard()).toContainText(names.partner);
  }

  await nav('Bestellungen');
  await page.getByLabel('Tisch oder Aktivität').selectOption(await page.getByLabel('Tisch oder Aktivität').locator('option').filter({ hasText: /^T01/ }).getAttribute('value'));
  await page.getByRole('button', { name: `${names.menu} hinzufügen`, exact: true }).click();
  for (let count = 1; count < 30; count++) await page.getByRole('button', { name: `${names.menu} mehr`, exact: true }).click();
  const order = await write(() => page.getByRole('button', { name: 'An Küche & Bar senden', exact: true }).click(), '/orders');
  expect(order.total_cents).toBe(30000);
  await nav('Küche & Bar'); await page.getByRole('button', { name: 'Küche', exact: true }).click();
  for (const status of ['Starten', 'Fertig', 'Servieren']) await write(() => page.getByRole('button', { name: `${names.menu}: ${status}`, exact: true }).click(), '/status', 200);
  await nav('Kasse'); await page.getByLabel('Neue Bargeldkasse', { exact: true }).fill(names.till);
  const register = await write(() => page.getByRole('button', { name: 'Kasse anlegen', exact: true }).click(), '/cash/registers');
  await page.getByLabel('Bargeldkasse', { exact: true }).selectOption(register.id); await page.getByLabel('Verantwortliche Bedienung').selectOption({ label: 'Test Leitung' });
  await page.getByLabel('Gezählter Anfangsbestand in €').fill('100');
  const session = await write(() => page.getByRole('button', { name: 'Schichtkasse öffnen', exact: true }).click(), '/cash/sessions');
  await page.getByLabel('Offene Schichtkasse').selectOption(session.id); await page.getByLabel('Bon kassieren oder Zahlung ansehen').selectOption(order.id);
  await page.getByLabel('Teilbetrag in €').fill('300'); await write(() => page.getByRole('button', { name: 'Erhaltenes Bargeld bestätigen', exact: true }).click(), '/cash-payments', 200);
  await nav('Partnerabrechnung'); await page.getByRole('tab', { name: 'Verkäufe & Rückgaben', exact: true }).click(); await page.getByLabel('Bon', { exact: true }).selectOption(order.id);
  const salePayloads = await loseFirstAnswer('**/api/gastro/venues/*/partners/sales');
  await write(() => page.getByRole('button', { name: 'Verkauf übernehmen', exact: true }).click(), '/partners/sales', 503);
  await page.reload(); await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' }); await nav('Partnerabrechnung');
  const sales = await write(() => page.getByRole('button', { name: 'Ausstehenden Auftrag erneut prüfen', exact: true }).click(), '/partners/sales');
  expect(salePayloads).toHaveLength(2); expect(salePayloads[1]).toEqual(salePayloads[0]); expect(sales.events).toHaveLength(30);
  await page.getByRole('tab', { name: 'Verkäufe & Rückgaben', exact: true }).click();
  for (const [kind, amount] of [['return', '5'], ['waste', '2']]) {
    await page.getByRole('button', { name: 'Eigentümerrückgabe / Bruch', exact: true }).click(); await modal().getByLabel('Vertrag', { exact: true }).selectOption(contract.id);
    await modal().getByLabel('Vorgang', { exact: true }).selectOption(kind); await modal().getByLabel('Menge in Lager-Basiseinheit').fill(amount); await modal().getByLabel('Begründung', { exact: true }).fill(`Geprüfte ${kind} Partnerware`);
    const result = await submit('Speichern', '/partners/stock'); if (kind === 'waste') expect(result.events[0].loss_cents).toBe(400);
  }
  await page.getByRole('tab', { name: 'Abrechnung', exact: true }).click(); await partnerCard().getByRole('button', { name: /^Monat .* prüfen$/ }).click();
  await expect(modal()).toContainText('39,00'); await expect(modal().getByRole('button', { name: 'Monat unveränderlich abschließen', exact: true })).toBeDisabled(); await modal().getByRole('button', { name: 'Dialog schließen', exact: true }).click();
  await nav('Lager & Waren'); await page.getByRole('button', { name: 'Bestände', exact: true }).click(); await expect(stockRow(names.partnerItem)).toContainText('63 Stück');
  await screenshot('partner-100-30-5-2-gleich-63');
  report.checks.push('100 Partnereinheiten erhalten; 30 bestätigte Verkäufe nach Commit503/Reload exakt einmal übernommen; 5 Eigentümerrückgaben und2 Bruch ergeben63 physisch und39 € Vertragsbetrag. Laufender Monat bleibt vor Abschluss geschützt.');

  await nav('Kasse'); await page.getByLabel('Offene Schichtkasse').selectOption(session.id); await page.getByLabel('Bon kassieren oder Zahlung ansehen').selectOption(order.id);
  const cashSale = page.locator('.fp-run').filter({ has: page.getByLabel('Rückerstattung in €') }); await expect(cashSale).toHaveCount(1); await cashSale.locator('summary').click();
  await cashSale.getByLabel('Rückerstattung in €').fill('300'); await cashSale.getByLabel('Grund', { exact: true }).fill('Vollständige Geldreklamation, Ware bereits serviert');
  await write(() => cashSale.getByRole('button', { name: 'Tatsächliche Barauszahlung bestätigen', exact: true }).click(), '/refunds');
  await nav('Partnerabrechnung'); await page.getByRole('tab', { name: 'Verkäufe & Rückgaben', exact: true }).click(); await page.getByLabel('Bon', { exact: true }).selectOption(order.id);
  const refunds = await write(() => page.getByRole('button', { name: 'Abrechnung korrigieren', exact: true }).click(), '/partners/refunds');
  expect(refunds.events.reduce((sum, event) => sum + event.gross_cents, 0)).toBe(-30000); expect(refunds.events.every(event => Number(event.physical_quantity) === 0 && !event.stock_operation_id)).toBe(true);
  await page.getByRole('tab', { name: 'Abrechnung', exact: true }).click(); await partnerCard().getByRole('button', { name: /^Monat .* prüfen$/ }).click(); await expect(modal()).toContainText('9,00'); await modal().getByRole('button', { name: 'Dialog schließen', exact: true }).click();
  await nav('Lager & Waren'); await expect(stockRow(names.partnerItem)).toContainText('63 Stück');
  report.checks.push('Vollständiger Cash-Refund korrigiert ausschließlich den Partnerbetrag auf9 €; servierte Ware wird nicht zurückgelagert, Bestand bleibt63.');

  await page.getByRole('button', { name: 'Reservierter Bestand', exact: true }).click(); await page.getByRole('button', { name: 'Reservierung', exact: true }).click();
  const option = await modal().getByLabel('Freie Charge und Lagerort').locator('option').filter({ hasText: names.ownItem }).getAttribute('value');
  await modal().getByLabel('Freie Charge und Lagerort').selectOption(option); await modal().getByLabel('Zu reservierende Menge').fill('8'); await modal().getByLabel('Konkreter Zweck').fill(`Buffet-Unterdeckung ${tag}`);
  const holdPayloads = await loseFirstAnswer('**/api/gastro/venues/*/inventory/reservations'); await submit('Reservieren', '/inventory/reservations', 503); await expect(modal().getByLabel('Zu reservierende Menge')).toBeDisabled();
  await page.reload(); await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' }); await nav('Lager & Waren'); await page.getByRole('button', { name: 'Reservierter Bestand', exact: true }).click();
  await write(() => page.getByRole('button', { name: 'Ausstehenden Auftrag erneut prüfen', exact: true }).click(), '/inventory/reservations');
  expect(holdPayloads).toHaveLength(2); expect(holdPayloads[1]).toEqual(holdPayloads[0]);
  await page.getByRole('button', { name: 'Bestände', exact: true }).click(); await expect(stockRow(names.ownItem)).toContainText('Reserviert: 8'); await expect(stockRow(names.ownItem)).toContainText('Frei verfügbar: 2');
  await stockRow(names.ownItem).getByRole('button', { name: `${names.ownItem} zählen`, exact: true }).click(); await modal().getByLabel('Tatsächlich gezählt in kg').fill('6'); await modal().getByLabel('Begründung', { exact: true }).fill('Tatsächlich vier kg weniger als erwartet'); await submit('Buchung bestätigen', '/counts');
  await expect(stockRow(names.ownItem)).toContainText('6 kg'); await expect(stockRow(names.ownItem)).toContainText('Reservierung ungedeckt: 2');
  await page.getByRole('button', { name: 'Reservierter Bestand', exact: true }).click();
  const shortHold = stockRow(`Buffet-Unterdeckung ${tag}`); await expect(shortHold).toContainText('Unterdeckt'); await expect(shortHold).toContainText('2 fehlen'); await expect(shortHold.getByRole('button', { name: 'Manuell verbrauchen', exact: true })).toBeDisabled();
  await screenshot('reservierung-inventur-echte-unterdeckung');
  await shortHold.getByRole('button', { name: 'Freigeben', exact: true }).click(); await modal().getByLabel('Begründung', { exact: true }).fill('Buffetbedarf neu geplant'); await submit('Freigeben', '/close');
  await page.getByRole('button', { name: 'Reservierung', exact: true }).click(); await modal().getByLabel('Freie Charge und Lagerort').selectOption(option); await modal().getByLabel('Zu reservierende Menge').fill('4'); await modal().getByLabel('Konkreter Zweck').fill(`Gedecktes Buffet ${tag}`); await submit('Reservieren', '/inventory/reservations');
  await page.getByRole('button', { name: 'Bestände', exact: true }).click(); await stockRow(names.ownItem).getByRole('button', { name: `Charge HOLD-LOT-${tag} sperren`, exact: true }).click(); await modal().getByLabel('Begründung', { exact: true }).fill('Liefercharge vorsorglich prüfen'); await submit('Buchung bestätigen', '/quarantine');
  await page.getByRole('button', { name: 'Reservierter Bestand', exact: true }).click(); await expect(stockRow(`Gedecktes Buffet ${tag}`).getByRole('button', { name: 'Manuell verbrauchen', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Bestände', exact: true }).click(); await stockRow(names.ownItem).getByRole('button', { name: `Charge HOLD-LOT-${tag} freigeben`, exact: true }).click(); await modal().getByLabel('Begründung', { exact: true }).fill('Charge vollständig geprüft und freigegeben'); await submit('Buchung bestätigen', '/quarantine');
  await page.getByRole('button', { name: 'Reservierter Bestand', exact: true }).click(); await stockRow(`Gedecktes Buffet ${tag}`).getByRole('button', { name: 'Manuell verbrauchen', exact: true }).click(); await modal().getByLabel('Produktions- oder Verbrauchsbeleg').fill(`BUFFET-${tag}`); await modal().getByLabel('Begründung', { exact: true }).fill('Manuelle Buffetvorbereitung aus eigener Ware'); await submit('Verbrauch buchen', '/close');
  await page.getByRole('button', { name: 'Bestände', exact: true }).click(); await expect(stockRow(names.ownItem)).toContainText('2 kg'); await expect(stockRow(names.ownItem)).toContainText('Frei verfügbar: 2');
  report.checks.push('Hold8 auf10 kg überlebt Commit503/Reload ohne Doppelreservierung. Zählung6 bleibt buchbar und zeigt Fehlmenge2; unterdeckter Verbrauch gesperrt. Freigabe, neuer Hold4, Quarantäne und Freigabe: erst danach referenzierter Verbrauch, Rest2 kg.');

  await nav('Partnerabrechnung'); await page.getByRole('tab', { name: 'Leihgut & Pfand', exact: true }).click(); await page.getByRole('button', { name: 'Leihkonto anlegen', exact: true }).click();
  await modal().getByLabel('Partner-Eigentümer').selectOption(owners[0].id); await modal().getByLabel('Bezeichnung').fill(names.loan); await modal().getByLabel('Kontoreferenz / Seriennummer').fill(`CRATES-${tag}`); await modal().getByLabel('Pfand pro Stück in Euro').fill('2'); await submit('Speichern', '/loans');
  for (const [kind, value] of [['received', '10'], ['deposit_paid', '20'], ['returned', '3'], ['deposit_refunded', '6'], ['broken', '1'], ['deposit_forfeited', '2']]) {
    await loanCard().getByRole('button', { name: 'Bewegung / Pfand buchen', exact: true }).click(); await modal().getByLabel('Vorgang', { exact: true }).selectOption(kind);
    if (['received', 'returned', 'broken'].includes(kind)) await modal().getByLabel('Stückzahl').fill(value);
    else { await modal().getByLabel('Betrag in Euro').fill(value); await modal().getByLabel('Externer Zahlungs- oder Verfallsbeleg').fill(`${kind}-${tag}`); }
    await modal().getByLabel('Begründung', { exact: true }).fill(`Geprüfter Leihvorgang ${kind}`); await submit('Speichern', '/loan-entries');
  }
  await expect(loanCard()).toContainText('6 vorhanden'); await expect(loanCard()).toContainText('Pfandforderung 12,00'); await screenshot('leihgut-pfand-getrennte-salden');
  report.checks.push('10 Leihkisten,20 € Pfandzahlung,3 Rückgaben mit6 € Rückzahlung,1 Bruch und2 € Pfandverfall:6 Gegenstände und12 € Pfandforderung bleiben getrennt nachvollziehbar.');
  await page.setViewportSize({ width: 390, height: 844 }); await loanCard().scrollIntoViewIfNeeded(); await screenshot('partner-pfand-mobile');
  await page.setViewportSize({ width: 1440, height: 1050 });
  await nav('Kasse'); const till = page.locator('details.fp-run').filter({ hasText: names.till }); await till.locator('summary').click(); await till.getByLabel('Gezähltes Bargeld in €').fill('100'); await write(() => till.getByRole('button', { name: 'Zählung festschreiben', exact: true }).click(), '/count', 200); await till.getByLabel('Differenzbegründung / Abschlussnotiz').fill('Partnerprüfung inklusive vollständigem Refund, ohne Differenz'); await write(() => till.getByRole('button', { name: 'Abschluss freigeben', exact: true }).click(), '/close', 200);
  expect(report.errors).toEqual([]);
} catch (error) { report.failure = error.stack; const path = `${output}/failure.png`; await page.screenshot({ path, fullPage: true }).catch(() => {}); report.screenshots.push({ path }); }
finally { await fs.writeFile(`${output}/report.json`, JSON.stringify(report, null, 2)); await browser.close(); }
console.log(JSON.stringify(report, null, 2));
if (report.failure) process.exitCode = 1;
