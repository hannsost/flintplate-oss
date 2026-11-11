import { chromium, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import { fulfillFromIsolatedApi, requestIsolatedApi } from './flintplate-browser-api.mjs';

// Every API request, including authentication and writes, stays on the isolated
// acceptance socket. This script must never fall back to the demo API.
const socket = process.env.FLINTPLATE_BROWSER_SOCKET;
if (!socket) throw new Error('FLINTPLATE_BROWSER_SOCKET is required; real/demo API writes are forbidden.');
const credentials = JSON.parse(await fs.readFile(process.env.FLINTPLATE_BROWSER_CREDENTIALS ?? new URL('../../backend/.local/browser-acceptance-access.json', import.meta.url), 'utf8'));
const output = '/tmp/hireos-browser-tests/flintplate-erp-acceptance';
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH ?? '/tmp/palmscout-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell', headless: true, args: ['--disable-gpu', '--disable-dev-shm-usage', '--no-sandbox'] });
const context = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 1440, height: 1050 }, timezoneId: 'Europe/Berlin' });
const page = await context.newPage();
page.setDefaultTimeout(45000);
const report = { isolated: true, checks: [], screenshots: [], errors: [], writes: [] };
page.on('pageerror', error => report.errors.push(error.message));
await context.route('**/*', async route => {
  const request = route.request();
  const url = new URL(request.url());
  if (url.origin !== 'http://localhost:3012' || !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
    report.errors.push(`Blocked unproxied request: ${request.method()} ${url.pathname}`);
    await route.abort('blockedbyclient');
  } else await route.continue();
});
await context.route('**/api/**', route => fulfillFromIsolatedApi(route, socket));
async function shot(name) {
  await page.evaluate(async () => { await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => undefined))); });
  const path = `${output}/${name}.png`;
  await page.screenshot({ path, fullPage: true });
  report.screenshots.push(path);
}
async function nav(name) {
  await page.getByRole('navigation', { name: 'Betriebsnavigation' }).getByRole('button', { name, exact: false }).click();
  await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
}
async function post(click, suffix, allowError = false) {
  const [result] = await Promise.all([page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith(suffix)), click()]);
  const json = await result.json();
  report.writes.push({ path: new URL(result.url()).pathname, status: result.status() });
  console.log(JSON.stringify({ checkpoint: suffix, status: result.status() }));
  if (!allowError) expect(result.ok(), JSON.stringify(json)).toBe(true);
  await expect(page.getByRole('button', { name: 'Daten aktualisieren', exact: true })).toBeEnabled();
  return json;
}
async function dialogPost(suffix) {
  const result = await post(() => page.getByRole('dialog').getByRole('button', { name: /^(Anlegen|Buchung bestätigen|Verbindlich speichern)$/ }).click(), suffix);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  return result;
}
try {
  await page.goto('http://localhost:3012/anmelden?next=%2Fgastro');
  await page.getByLabel('E-Mail-Adresse').fill(credentials.manager);
  await page.getByLabel('Passwort', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await page.waitForURL('**/gastro');
  await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await nav('Bestellungen');
  await page.getByLabel('Tisch oder Aktivität').selectOption(await page.getByLabel('Tisch oder Aktivität').locator('option').filter({ hasText: /^T01/ }).getAttribute('value'));
  await page.getByRole('button', { name: 'Testgericht hinzufügen', exact: true }).click({ clickCount: 2 });
  await page.getByLabel('Hinweis zur Bestellung', { exact: true }).fill('Isolierter Serviceablauf');
  const order = await post(() => page.getByRole('button', { name: 'An Küche & Bar senden', exact: true }).click(), '/orders');
  expect(order.total_cents).toBe(2000);
  await nav('Küche & Bar');
  await page.getByRole('button', { name: 'Küche', exact: true }).click();
  for (const name of ['Starten', 'Fertig', 'Servieren']) {
    await post(() => page.getByRole('button', { name: `Testgericht: ${name}`, exact: true }).click(), '/status');
  }
  await nav('Bestellungen');
  await page.locator('.fp-kitchen-ticket').filter({ hasText: order.number }).getByRole('button', { name: 'Nachbestellen', exact: true }).click();
  await page.getByRole('button', { name: 'Wasser hinzufügen', exact: true }).click();
  const appended = await post(() => page.getByRole('button', { name: `Auf ${order.number} nachbestellen`, exact: true }).click(), '/append');
  expect(appended.id).toBe(order.id);
  expect(appended.total_cents).toBe(2300);
  expect(appended.lines.find(line => line.name === 'Testgericht').preparation_status).toBe('served');
  await nav('Küche & Bar');
  await page.getByRole('button', { name: 'Bar', exact: true }).click();
  for (const name of ['Starten', 'Fertig', 'Servieren']) {
    await post(() => page.getByRole('button', { name: `Wasser: ${name}`, exact: true }).click(), '/status');
  }
  await nav('Bestellungen');
  await page.locator('.fp-kitchen-ticket').filter({ hasText: order.number }).getByRole('button', { name: 'Tisch wechseln', exact: true }).click();
  await page.getByLabel('Neuer Tisch').selectOption(await page.getByLabel('Neuer Tisch').locator('option').filter({ hasText: /^T02/ }).getAttribute('value'));
  await post(() => page.getByRole('button', { name: 'Bon auf diesen Tisch verschieben', exact: true }).click(), '/transfer');
  await expect(page.locator('.fp-kitchen-ticket').filter({ hasText: order.number })).toContainText('T02');
  await shot('service-nachbestellung-tischwechsel');
  report.checks.push('T01: 2× Testgericht → Küche einzeln serviert → Wasser auf denselben Bon nachbestellt → Bar einzeln serviert → kompletter Bon nach T02.');

  await nav('Kasse');
  await page.getByLabel('Neue Bargeldkasse', { exact: true }).fill('Browserkasse');
  const register = await post(() => page.getByRole('button', { name: 'Kasse anlegen', exact: true }).click(), '/cash/registers');
  await page.getByLabel('Bargeldkasse', { exact: true }).selectOption(register.id);
  await page.getByLabel('Verantwortliche Bedienung').selectOption({ label: 'Test Leitung' });
  await page.getByLabel('Gezählter Anfangsbestand in €').fill('100');
  const session = await post(() => page.getByRole('button', { name: 'Schichtkasse öffnen', exact: true }).click(), '/cash/sessions');
  await page.getByLabel('Offene Schichtkasse').selectOption(session.id);
  await page.getByLabel('Bon kassieren oder Zahlung ansehen').selectOption(order.id);
  await page.getByLabel('Teilbetrag in €').fill('8.50');
  await page.getByLabel('Gegeben in € (optional, für Rückgeld)').fill('10');
  await post(() => page.getByRole('button', { name: 'Erhaltenes Bargeld bestätigen', exact: true }).click(), '/cash-payments');
  await expect(page.getByText(/Rückgeld: 1,50/)).toBeVisible();
  await page.getByRole('button', { name: 'Personen', exact: true }).click();
  await page.getByLabel('Verbleibende Personen').fill('2');
  await post(() => page.getByRole('button', { name: 'Erhaltenes Bargeld bestätigen', exact: true }).click(), '/cash-payments');
  await page.getByRole('button', { name: 'Betrag', exact: true }).click();
  await expect(page.getByLabel('Teilbetrag in €')).toHaveValue('7.25');
  await post(() => page.getByRole('button', { name: 'Erhaltenes Bargeld bestätigen', exact: true }).click(), '/cash-payments');
  await expect(page.getByLabel('Teilbetrag in €')).toHaveCount(0);
  const firstSale = page.locator('.fp-run').filter({ has: page.getByText(/Rückgeld: 1,50/) });
  await firstSale.locator('summary').click();
  await firstSale.getByLabel('Rückerstattung in €').fill('1');
  await firstSale.getByLabel('Grund', { exact: true }).fill('Isolierte Testkorrektur');
  await post(() => firstSale.getByRole('button', { name: 'Tatsächliche Barauszahlung bestätigen', exact: true }).click(), '/refunds');
  await expect(page.getByText(/Zurückerstattet: 1,00/)).toBeVisible();
  await shot('kasse-split-rueckgeld-erstattung');
  const sessionPanel = page.locator('details.fp-run').filter({ hasText: 'Browserkasse' });
  await sessionPanel.locator('summary').click();
  await sessionPanel.getByLabel('Einlage (+) / Entnahme (−) in €').fill('5');
  await sessionPanel.getByLabel('Grund', { exact: true }).fill('Isolierte Prüfeinlage');
  await post(() => sessionPanel.getByRole('button', { name: 'Bewegung bestätigen', exact: true }).click(), '/movements');
  await sessionPanel.getByLabel('Gezähltes Bargeld in €').fill('127');
  await post(() => sessionPanel.getByRole('button', { name: 'Zählung festschreiben', exact: true }).click(), '/count');
  await expect(sessionPanel).toContainText('Differenz 0,00');
  await sessionPanel.getByLabel('Differenzbegründung / Abschlussnotiz').fill('Browserprüfung ohne Differenz');
  await post(() => sessionPanel.getByRole('button', { name: 'Abschluss freigeben', exact: true }).click(), '/close');
  await expect(sessionPanel).toContainText('abgeschlossen');
  await page.getByRole('button', { name: 'Abgleich laden', exact: true }).click();
  await expect(page.getByText(/0 Schichtkassen noch nicht abgeschlossen/)).toBeVisible();
  await shot('kasse-blindzaehlung-tagesabgleich');
  report.checks.push('100 € Kassenöffnung + 23 € in drei Teilzahlungen − 1 € Erstattung + 5 € Einlage = 127 €; 1,50 € Rückgeld, Blindzählung und Abschluss ohne Differenz.');

  await nav('Lager & Waren');
  await page.getByRole('button', { name: 'Artikel & Orte', exact: true }).click();
  for (const [sku, name, unit] of [['BROWSER-RAW', 'Basiszutat', 'kg'], ['BROWSER-PREP', 'Prepportion', 'piece']]) {
    await page.getByRole('button', { name: 'Artikel', exact: true }).click();
    await page.getByLabel('Lagernummer').fill(sku);
    await page.getByLabel('Artikelname').fill(name);
    await page.getByLabel('Basiseinheit').selectOption(unit);
    if (unit === 'kg') await page.getByLabel('MHD beim Wareneingang erforderlich').check();
    await dialogPost('/items');
  }
  await page.getByRole('button', { name: 'Eigentümer', exact: true }).click();
  await page.getByLabel('Name des Eigentümers').fill('Eigenbetrieb');
  const owner = await dialogPost('/owners');
  await page.getByRole('button', { name: 'Lagerort', exact: true }).click();
  await page.getByLabel('Name des Lagerorts').fill('Kühlhaus');
  const location = await dialogPost('/locations');
  await page.getByRole('button', { name: 'Wareneingang', exact: true }).click();
  await page.getByLabel('Lagerartikel', { exact: true }).selectOption({ label: 'Basiszutat · kg' });
  await page.getByLabel('Eigentümer dieser Ware').selectOption(owner.id);
  await page.getByLabel('Lagerort', { exact: true }).selectOption(location.id);
  await page.getByLabel('Liefercharge').fill('RAW-BROWSER');
  await page.getByLabel('Menge in kg').fill('10');
  await page.getByLabel('MHD', { exact: true }).fill(new Date(Date.now() + 31 * 86400000).toISOString().slice(0, 10));
  await page.getByLabel('Lieferschein / Referenz').fill('LS-BROWSER');
  const receiptPayloads = [];
  await page.route('**/api/gastro/venues/*/inventory/receipts', async route => {
    receiptPayloads.push(route.request().postDataJSON());
    const response = await requestIsolatedApi(route.request(), socket);
    if (receiptPayloads.length === 1) {
      expect(response.status).toBeLessThan(300);
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Prüfung: Eingang gebucht, Antwort gezielt verloren.' }) });
    } else await route.fulfill(response);
  });
  await post(() => page.getByRole('button', { name: 'Buchung bestätigen', exact: true }).click(), '/receipts', true);
  await page.reload();
  await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await nav('Lager & Waren');
  await expect(page.getByRole('button', { name: 'Wareneingang', exact: true })).toBeDisabled();
  await post(() => page.getByRole('button', { name: 'Lagerbuchung erneut prüfen', exact: true }).click(), '/receipts');
  expect(receiptPayloads.length).toBe(2);
  expect(receiptPayloads[1]).toEqual(receiptPayloads[0]);
  await expect(page.getByRole('row').filter({ hasText: 'RAW-BROWSER' })).toContainText('10 kg');
  report.checks.push('Wareneingang wurde tatsächlich gebucht, Antwort abgefangen; Reload und identischer Retry belassen genau 10 kg statt Doppelbestand.');

  await nav('Produktion & Hygiene');
  await page.getByRole('button', { name: 'Rezeptur anlegen', exact: true }).click();
  await page.getByLabel('Rezeptname').fill('Basis-Prep');
  await page.getByLabel('Ausgabeartikel im Lager').selectOption({ label: 'Prepportion (Stück)' });
  await page.getByLabel('Geplante Ausbeute').fill('5');
  await page.getByRole('dialog').getByLabel('Lagerartikel', { exact: true }).selectOption({ label: 'Basiszutat (kg)' });
  await page.getByLabel('Menge in Basiseinheit').fill('1');
  await page.getByLabel('Netto-Einstandskosten je Basiseinheit in Cent').fill('200');
  await page.getByLabel('Mengen und Allergene anhand der Zutaten und Lieferantenangaben geprüft.').check();
  await page.getByLabel('Allergene, mit Komma getrennt').fill('gluten, milch');
  const recipe = await post(() => page.getByLabel('Allergene, mit Komma getrennt').press('Enter'), '/recipes');
  expect(recipe.allergens).toEqual(expect.arrayContaining(['gluten', 'milch']));
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Mise en place', exact: true }).click();
  await page.getByRole('button', { name: 'Produktion buchen', exact: true }).click();
  await page.getByLabel('Rezeptversion').selectOption(recipe.id);
  await page.getByLabel('Tatsächliche Ausbeute').fill('4');
  await page.getByLabel('Eigentümer', { exact: true }).selectOption(owner.id);
  await page.getByLabel('Ziellager').selectOption(location.id);
  await page.getByLabel('Neue Chargennummer').fill('PREP-BROWSER');
  await page.getByLabel('MHD laut Hygienekonzept').fill(new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10));
  const prepPayloads = [];
  await page.route('**/api/gastro/venues/*/prep', async route => {
    if (route.request().method() !== 'POST') { await route.fallback(); return; }
    prepPayloads.push(route.request().postDataJSON());
    const response = await requestIsolatedApi(route.request(), socket);
    if (prepPayloads.length === 1) {
      expect(response.status).toBeLessThan(300);
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Prüfung: Produktion gebucht, Antwort gezielt verloren.' }) });
    } else await route.fulfill(response);
  });
  await post(() => page.getByRole('dialog').getByRole('button', { name: 'Verbindlich speichern', exact: true }).click(), '/prep', true);
  await page.reload();
  await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await nav('Produktion & Hygiene');
  await expect(page.getByRole('button', { name: 'Rezeptur anlegen', exact: true })).toBeDisabled();
  await post(() => page.getByRole('button', { name: 'Produktionsvorgang erneut prüfen', exact: true }).click(), '/prep');
  expect(prepPayloads).toHaveLength(2);
  expect(prepPayloads[1]).toEqual(prepPayloads[0]);
  await page.getByRole('button', { name: 'Mise en place', exact: true }).click();
  await expect(page.getByText(/4.*Einheiten produziert/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Produktion buchen', exact: true })).toBeEnabled();
  await shot('produktion-tatsaechliche-ausbeute');
  await page.getByRole('button', { name: 'Hygiene', exact: true }).click();
  await page.getByRole('button', { name: 'Kontrolle erfassen', exact: true }).click();
  await page.getByLabel('Kontrolle', { exact: true }).fill('Kühltemperatur');
  await page.getByLabel('Ort / Gerät').fill('Kühlhaus');
  await page.getByLabel('Messwert').fill('10');
  await page.getByLabel('Betriebliche Untergrenze').fill('0');
  await page.getByLabel('Betriebliche Obergrenze').fill('7');
  await page.getByLabel('Sofortmaßnahme bei Abweichung').fill('Ware gesperrt und Kühlung überprüft.');
  await dialogPost('/haccp');
  await page.getByRole('button', { name: 'Nachkontrolle', exact: true }).click();
  await page.getByLabel('Messwert').fill('4');
  await dialogPost('/haccp');
  await expect(page.getByRole('button', { name: 'Nachkontrolle', exact: true })).toHaveCount(0);
  await expect(page.getByText('Im Soll', { exact: true })).toBeVisible();
  await shot('hygiene-abweichung-nachkontrolle');
  report.checks.push('Rezept per Enter mit Allergenen gespeichert; 1 kg Zutat ergibt 4 Prepportionen tatsächliche Ausbeute. Hygieneabweichung mit Maßnahme und erfolgreicher verknüpfter Nachkontrolle.');

  await nav('Lager & Waren');
  await expect(page.getByRole('row').filter({ hasText: 'RAW-BROWSER' })).toContainText('9 kg');
  await expect(page.getByRole('row').filter({ hasText: 'PREP-BROWSER' })).toContainText('4 Stück');
  await page.getByRole('button', { name: 'Charge RAW-BROWSER rückverfolgen', exact: true }).click();
  await expect(page.getByText('2 verbundene Chargen', { exact: true })).toBeVisible();
  await expect(page.getByRole('dialog')).toContainText('PREP-BROWSER');
  await page.getByLabel('Grund des Rückrufs').fill('Lieferantenrückruf im isolierten Test');
  await post(() => page.getByRole('button', { name: '2 Chargen sperren', exact: true }).click(), '/recall');
  await expect(page.getByRole('dialog').getByRole('status')).toContainText('2 Chargen sind gesperrt');
  await shot('chargenrueckruf-folgecharge');
  await page.getByRole('button', { name: 'Dialog schließen', exact: true }).click();
  await expect(page.getByRole('row').filter({ hasText: 'RAW-BROWSER' })).toContainText('Quarantäne');
  await expect(page.getByRole('row').filter({ hasText: 'PREP-BROWSER' })).toContainText('Quarantäne');
  report.checks.push('Rückverfolgung verbindet Eingangs- und Prepcharge; ein Rückruf sperrt beide Chargen mit Referenz und Begründung.');

  await nav('Einkauf');
  await page.getByRole('button', { name: 'Lieferanten & Katalog', exact: true }).click();
  await page.getByRole('button', { name: 'Lieferant', exact: true }).click();
  await page.getByLabel('Lieferantenname').fill('Browserlieferant');
  await page.getByLabel('Kundennummer / Referenz').fill('KD-BROWSER');
  await post(() => page.getByRole('dialog').getByRole('button', { name: 'Bestätigen', exact: true }).click(), '/suppliers');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Lieferartikel', exact: true }).click();
  await page.getByLabel('Lagerartikel', { exact: true }).selectOption({ label: 'Basiszutat · kg' });
  await page.getByLabel('Artikelnummer beim Lieferanten').fill('L-RAW');
  await page.getByLabel('Gebindename', { exact: true }).fill('Beutel');
  await page.getByLabel('Inhalt je Gebinde in kg').fill('2.5');
  await page.getByLabel('Nettopreis je Gebinde in €').fill('5');
  await page.getByLabel('Steuersatz in %', { exact: true }).fill('7');
  await post(() => page.getByRole('dialog').getByRole('button', { name: 'Bestätigen', exact: true }).click(), '/catalog');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Bestellung', exact: true }).click();
  await page.getByLabel('Basiszutat · Anzahl Beutel').fill('2');
  await page.getByLabel('Begründung / Notiz').fill('Isolierter Gebindeeinkauf');
  const purchase = await post(() => page.getByRole('dialog').getByRole('button', { name: 'Bestätigen', exact: true }).click(), '/orders');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('group', { name: 'Einkaufsansicht' }).getByRole('button', { name: 'Bestellungen', exact: true }).click();
  const purchaseCard = page.locator('section.fp-panel').filter({ has: page.getByRole('heading', { name: `${purchase.number} · Browserlieferant`, exact: true }) });
  await purchaseCard.getByRole('button', { name: 'Freigeben', exact: true }).click();
  await page.getByLabel('Begründung / Notiz').fill('Mengen und Preis geprüft');
  await post(() => page.getByRole('dialog').getByRole('button', { name: 'Bestätigen', exact: true }).click(), '/state');
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await purchaseCard.getByRole('button', { name: 'Annehmen', exact: true }).click();
  await page.getByLabel('Angenommen in kg').fill('2.5');
  await page.getByLabel('Liefercharge').fill('PURCHASE-BROWSER');
  await page.getByLabel('MHD', { exact: true }).fill(new Date(Date.now() + 31 * 86400000).toISOString().slice(0, 10));
  await page.getByLabel('Lieferschein / Referenz').fill('LS-PURCHASE');
  const purchasingReceipts = [];
  await page.route(`**/api/gastro/venues/*/purchasing/orders/${purchase.id}/receipts`, async route => {
    purchasingReceipts.push(route.request().postDataJSON());
    const response = await requestIsolatedApi(route.request(), socket);
    if (purchasingReceipts.length === 1) {
      expect(response.status).toBeLessThan(300);
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Prüfung: Teilannahme gebucht, Antwort gezielt verloren.' }) });
    } else await route.fulfill(response);
  });
  await post(() => page.getByRole('dialog').getByRole('button', { name: 'Bestätigen', exact: true }).click(), '/receipts', true);
  await page.reload();
  await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await nav('Einkauf');
  await post(() => page.getByRole('button', { name: 'Ausstehenden Vorgang erneut prüfen', exact: true }).click(), '/receipts');
  expect(purchasingReceipts).toHaveLength(2);
  expect(purchasingReceipts[1]).toEqual(purchasingReceipts[0]);
  await expect(page.getByRole('button', { name: 'Bestellung', exact: true })).toBeEnabled();
  await expect(purchaseCard).toContainText('Teillieferung');
  await expect(purchaseCard.locator('summary')).toHaveText('Wareneingänge (1)');
  await shot('einkauf-teilannahme-nach-retry');

  for (const [net, matched] of [['6', false], ['5', true]]) {
    await page.getByRole('group', { name: 'Einkaufsansicht' }).getByRole('button', { name: 'Bestellungen', exact: true }).click();
    await purchaseCard.getByRole('button', { name: 'Rechnung erfassen', exact: true }).click();
    await page.getByLabel('Rechnungsnummer').fill('RE-BROWSER');
    await page.getByRole('dialog').getByRole('checkbox', { name: `${purchase.number} · Basiszutat`, exact: true }).check();
    await page.getByLabel('Berechnete Menge in kg').fill('2.5');
    await page.getByLabel('Berechneter Nettobetrag in €').fill(net);
    const invoice = await post(() => page.getByRole('button', { name: 'Rechnung erfassen und vergleichen', exact: true }).click(), '/invoices');
    expect(invoice.check.matched).toBe(matched);
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await page.getByRole('button', { name: 'Rechnungsprüfung', exact: true }).click();
    const invoiceCard = page.locator('section.fp-panel').filter({ has: page.getByRole('heading', { name: 'RE-BROWSER · Browserlieferant', exact: true }) }).filter({ has: page.getByRole('button', { name: 'Fachlich freigeben', exact: true }) });
    if (matched) await invoiceCard.getByRole('button', { name: 'Fachlich freigeben', exact: true }).click();
    else {
      await expect(invoiceCard.getByRole('button', { name: 'Fachlich freigeben', exact: true })).toBeDisabled();
      await shot('einkauf-rechnungsdifferenz');
      await invoiceCard.getByRole('button', { name: 'Zurückweisen', exact: true }).click();
    }
    await page.getByLabel('Begründung / Notiz').fill(matched ? 'Korrigierter Preis und Teilmenge stimmen' : 'Nettopreis weicht vom bestellten Gebinde ab');
    await post(() => page.getByRole('dialog').getByRole('button', { name: 'Bestätigen', exact: true }).click(), '/decision');
    await expect(page.getByRole('dialog')).toHaveCount(0);
  }
  await expect(page.getByText('Fachlich freigegeben', { exact: true })).toBeVisible();
  await shot('einkauf-rechnung-korrigiert-freigegeben');
  await nav('Lager & Waren');
  await expect(page.getByRole('row').filter({ hasText: 'PURCHASE-BROWSER' })).toContainText('2,5 kg');
  report.checks.push('2×2,5-kg-Gebinde bestellt; Teilannahme mit verlorener Antwort und identischem Retry bleibt einmalig 2,5 kg. Falscher Rechnungspreis blockiert Freigabe, Korrektur nach Zurückweisung ist fachlich freigegeben.');
  expect(report.errors).toEqual([]);
} catch (error) {
  report.failed = String(error);
  await shot('failure-state').catch(() => undefined);
  process.exitCode = 1;
} finally {
  await context.close();
  await browser.close();
  await fs.writeFile(`${output}/report.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
}
