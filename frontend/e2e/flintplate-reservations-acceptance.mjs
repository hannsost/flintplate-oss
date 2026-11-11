import { chromium, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs/promises';
import { fulfillFromIsolatedApi, requestIsolatedApi } from './flintplate-browser-api.mjs';

// Run after the ERP acceptance journey against its isolated, synthetic tenant.
// Every mutation is performed through a visible control and the test API socket.
const socket = process.env.FLINTPLATE_BROWSER_SOCKET;
if (!socket) throw new Error('Isolated acceptance socket required; demo writes are forbidden.');
const credentials = JSON.parse(await fs.readFile(process.env.FLINTPLATE_BROWSER_CREDENTIALS ?? new URL('../../backend/.local/browser-acceptance-access.json', import.meta.url), 'utf8'));
const output = '/tmp/hireos-browser-tests/flintplate-reservations-acceptance';
await fs.mkdir(output, { recursive: true });
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
const card = name => page.locator('article.fp-panel').filter({ has: page.getByRole('heading', { name, exact: true }) });
const local = value => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Europe/Berlin', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(value).replace(' ', 'T');
async function nav(name) { await page.getByRole('navigation', { name: 'Betriebsnavigation' }).getByRole('button', { name, exact: true }).click(); await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' }); }
async function ready() { await expect(page.getByRole('button', { name: 'Spontane Gäste', exact: true })).toBeEnabled(); }
async function write(click, suffix, expected = 200, method = 'POST') {
  const [response] = await Promise.all([page.waitForResponse(response => response.request().method() === method && new URL(response.url()).pathname.endsWith(suffix)), click()]); const data = await response.json();
  report.writes.push({ path: new URL(response.url()).pathname, status: response.status() });
  console.log(JSON.stringify({ checkpoint: suffix, status: response.status() }));
  expect(response.status(), JSON.stringify(data)).toBe(expected);
  return data;
}
async function submit(label, suffix, expected = 200) {
  const data = await write(() => modal().getByRole('button', { name: label, exact: true }).click(), suffix, expected);
  if (expected < 300) { await expect(modal()).toHaveCount(0); await ready(); }
  return data;
}
async function table(label, name) {
  const select = modal().getByLabel(label, { exact: true });
  const value = await select.locator('option').filter({ hasText: new RegExp(`^${name} ·`) }).getAttribute('value');
  await select.selectOption(value); return value;
}
async function screenshot(name) {
  await page.evaluate(async () => { await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => undefined))); });
  const axe = await new AxeBuilder({ page }).include('.fp').withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
  const path = `${output}/${name}.png`; await page.screenshot({ path, fullPage: page.viewportSize().width > 700 });
  report.screenshots.push({ path, viewport: page.viewportSize(), overflow, violations: axe.violations.map(item => ({ id: item.id, targets: item.nodes.map(node => node.target) })) });
  expect(overflow).toBe(false); expect(axe.violations).toEqual([]);
}
try {
  await page.goto('http://localhost:3012/anmelden?next=%2Fgastro');
  await page.getByLabel('E-Mail-Adresse').fill(credentials.manager); await page.getByLabel('Passwort', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click(); await page.waitForURL('**/gastro');
  await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await nav('Räume & Aktivitäten');
  await page.getByRole('button', { name: /^T01, / }).click(); await modal().getByRole('button', { name: 'Ressource bearbeiten', exact: true }).click();
  await modal().getByLabel('T02 · 4 Plätze', { exact: true }).check();
  const savedTable = await write(() => modal().getByRole('button', { name: 'Speichern', exact: true }).click(), '', 200, 'PUT');
  expect(savedTable.combinable_with).toHaveLength(1); await expect(modal()).toHaveCount(0);
  await nav('Reservierungen'); await ready();
  await page.getByRole('button', { name: 'Spontane Gäste', exact: true }).click();
  await modal().getByLabel('Gast / Gruppe').fill('Browser Walk-in'); await table('Tisch', 'T01');
  await modal().getByLabel('Geplanter Aufenthalt in Minuten').fill('30');
  const walkin = await submit('Jetzt platzieren', '/reservation-groups', 201);
  expect(walkin.status).toBe('seated');
  await nav('Räume & Aktivitäten'); await expect(page.getByRole('button', { name: /T01, .*Anwesend · Browser Walk-in/ })).toBeVisible();
  report.checks.push('Manager verbindet T01 mit T02 über die Oberfläche; Walk-in belegt T01 sofort ohne Bestellung.');

  await nav('Reservierungen'); await ready();
  await page.getByRole('button', { name: 'Reservierung', exact: true }).click();
  await modal().getByLabel('Gast / Gruppe').fill('Browser Anschluss'); await table('Tisch oder Aktivität', 'T01');
  const arrival = new Date(Date.now() + 35 * 60000), finish = new Date(Date.now() + 65 * 60000);
  await modal().getByLabel(/^Beginn/).fill(local(arrival)); await modal().getByLabel(/^Ende/).fill(local(finish));
  const following = await submit('Verbindlich reservieren', '/reservation-groups', 201);
  await card('Browser Walk-in').getByRole('button', { name: 'Verlängern', exact: true }).click();
  await modal().getByRole('button', { name: '+60 Min.', exact: true }).click();
  await submit('Verlängerung bestätigen', `/${walkin.id}/extend`, 409);
  await expect(modal().getByRole('alert')).toBeVisible();
  await modal().getByLabel(/^Neues Ende/).fill(local(new Date(Date.now() + 32 * 60000)));
  const extended = await submit('Verlängerung bestätigen', `/${walkin.id}/extend`);
  expect(new Date(extended.ends_at).getTime()).toBeLessThan(new Date(following.starts_at).getTime());
  await card('Browser Walk-in').getByRole('button', { name: 'Aufenthalt beenden', exact: true }).click();
  await submit('Änderung bestätigen', `/${walkin.id}/state`);
  await card('Browser Anschluss').getByRole('button', { name: 'Stornieren', exact: true }).click();
  await submit('Änderung bestätigen', `/${following.id}/state`);
  report.checks.push('Verlängerung über eine Anschlussreservierung wird sichtbar abgelehnt; gültige Verlängerung, Abschluss und Storno gelingen.');

  await page.getByRole('button', { name: 'Warteliste', exact: true }).click();
  await modal().getByLabel('Gast / Gruppe').fill('Browser Tischgruppe'); await modal().getByLabel('Personen', { exact: true }).fill('6');
  await modal().getByLabel('Notiz (optional)').fill('Sechs Gäste sitzen gemeinsam.');
  const waiting = await submit('Auf Warteliste aufnehmen', '/waitlist', 201);
  await page.getByRole('button', { name: /^Warteliste ·/ }).click();
  await card('Browser Tischgruppe').getByRole('button', { name: 'Platz zuweisen', exact: true }).click();
  const primary = await table('Tisch', 'T01');
  await expect(modal().getByRole('button', { name: 'Jetzt platzieren', exact: true })).toBeDisabled();
  await modal().locator('summary').filter({ hasText: 'Weitere Tische verbinden' }).click();
  await modal().getByLabel('T02 · 4 Plätze', { exact: true }).check();
  const payloads = [];
  await page.route(`**/api/gastro/venues/*/waitlist/${waiting.id}/seat`, async route => {
    payloads.push(route.request().postDataJSON()); const response = await requestIsolatedApi(route.request(), socket);
    if (payloads.length === 1) { expect(response.status).toBe(201); await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Prüfung: Gäste platziert, Bestätigung gezielt verloren.' }) }); }
    else await route.fulfill(response);
  });
  await submit('Jetzt platzieren', `/${waiting.id}/seat`, 503);
  await expect(modal().getByLabel('Tisch', { exact: true })).toBeDisabled();
  await page.reload(); await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await nav('Reservierungen'); await expect(page.getByRole('button', { name: 'Spontane Gäste', exact: true })).toBeDisabled();
  const seated = await write(() => page.getByRole('button', { name: 'Reservierungsvorgang erneut prüfen', exact: true }).click(), `/${waiting.id}/seat`, 201);
  await ready(); expect(payloads).toHaveLength(2); expect(payloads[1]).toEqual(payloads[0]); expect(seated.table_ids).toHaveLength(2); expect(seated.table_ids).toContain(primary);
  const dayInput = page.getByLabel(/^Tag \(/); const today = await dayInput.inputValue();
  const nextDay = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/reservations/board') && new URL(response.url()).searchParams.has('start') && response.ok());
  await dayInput.fill(local(new Date(Date.now() + 86400000)).slice(0, 10)); await nextDay;
  await expect(card('Browser Tischgruppe')).toHaveCount(1); await expect(card('Browser Tischgruppe')).toContainText('Anwesend');
  const currentDay = page.waitForResponse(response => new URL(response.url()).pathname.endsWith('/reservations/board') && new URL(response.url()).searchParams.has('start') && response.ok());
  await dayInput.fill(today); await currentDay; await screenshot('gruppenreservierung-desktop');
  await nav('Räume & Aktivitäten');
  await expect(page.getByRole('button', { name: /T01, .*Anwesend · Browser Tischgruppe/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /T02, .*Anwesend · Browser Tischgruppe/ })).toBeVisible();
  await nav('Reservierungen'); await page.setViewportSize({ width: 390, height: 844 }); await card('Browser Tischgruppe').scrollIntoViewIfNeeded(); await screenshot('gruppenreservierung-mobil');
  await page.setViewportSize({ width: 1440, height: 1050 }); await ready();
  await card('Browser Tischgruppe').getByRole('button', { name: 'Aufenthalt beenden', exact: true }).click(); await submit('Änderung bestätigen', `/${seated.id}/state`);
  report.checks.push('Sechs Wartelistengäste benötigen zwei verbundene Tische. Tatsächlich gebuchte Platzierung übersteht verlorene Antwort und Reload mit identischem Payload/Key; beide Tische sind belegt, auch beim Datumswechsel.');

  await page.getByRole('button', { name: 'Reservierung', exact: true }).click();
  await modal().getByLabel('Gast / Gruppe').fill('Browser späte Ankunft'); await table('Tisch oder Aktivität', 'T01');
  await modal().getByLabel(/^Beginn/).fill(local(new Date(Date.now() - 45 * 60000))); await modal().getByLabel(/^Ende/).fill(local(new Date(Date.now() - 15 * 60000)));
  const lateArrival = await submit('Verbindlich reservieren', '/reservation-groups', 201);
  await card('Browser späte Ankunft').getByRole('button', { name: 'Verlängern', exact: true }).click();
  await modal().getByLabel(/^Neues Ende/).fill(local(new Date(Date.now() + 30 * 60000))); await submit('Verlängerung bestätigen', `/${lateArrival.id}/extend`);
  await write(() => card('Browser späte Ankunft').getByRole('button', { name: 'Einchecken', exact: true }).click(), `/${lateArrival.id}/state`); await ready();
  await expect(card('Browser späte Ankunft')).toContainText('Anwesend');
  await card('Browser späte Ankunft').getByRole('button', { name: 'Aufenthalt beenden', exact: true }).click(); await submit('Änderung bestätigen', `/${lateArrival.id}/state`);
  report.checks.push('Verspätete bestätigte Reservierung lässt sich vor dem Einchecken verlängern und danach mit einem Klick einchecken.');

  await page.getByRole('button', { name: 'Reservierung', exact: true }).click();
  await modal().getByLabel('Gast / Gruppe').fill('Browser No-show'); await table('Tisch oder Aktivität', 'T01');
  await modal().getByLabel(/^Beginn/).fill(local(new Date(Date.now() - 15 * 60000))); await modal().getByLabel(/^Ende/).fill(local(new Date(Date.now() + 30 * 60000)));
  const absent = await submit('Verbindlich reservieren', '/reservation-groups', 201);
  await card('Browser No-show').getByRole('button', { name: 'Nicht erschienen', exact: true }).click();
  const closed = await submit('Änderung bestätigen', `/${absent.id}/state`); expect(closed.status).toBe('no_show');
  await page.getByRole('button', { name: 'Erledigt', exact: true }).click(); await expect(card('Browser No-show')).toContainText('Nicht erschienen');
  await screenshot('reservierungen-abschluesse'); report.checks.push('No-show lässt sich nach Beginn ausdrücklich erfassen; abgeschlossene Gruppen und Stornos bleiben im Tagesverlauf sichtbar.');
  expect(report.errors).toEqual([]);
} catch (error) { report.failure = error.stack; const path = `${output}/failure.png`; await page.screenshot({ path, fullPage: true }).catch(() => {}); report.screenshots.push({ path }); }
finally { await fs.writeFile(`${output}/report.json`, JSON.stringify(report, null, 2)); await browser.close(); }
console.log(JSON.stringify(report, null, 2));
if (report.failure) process.exitCode = 1;
