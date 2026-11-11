import { chromium, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs/promises';
import { fulfillFromIsolatedApi, requestIsolatedApi } from './flintplate-browser-api.mjs';

// UI regression: business writes are intercepted. The 503/retry is deliberate;
// backend idempotency, venue authorization and KDS mutations are tested separately.
const credentials = JSON.parse(await fs.readFile(process.env.FLINTPLATE_BROWSER_CREDENTIALS ?? new URL('../../backend/.local/demo-access.json', import.meta.url), 'utf8'));
const base = 'http://localhost:3012';
const socketPath = process.env.FLINTPLATE_BROWSER_SOCKET;
const root = '/tmp/hireos-browser-tests/flintplate-draft-ux';
await fs.mkdir(root, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH ?? '/tmp/palmscout-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell', headless: true, args: ['--disable-gpu', '--disable-dev-shm-usage', '--no-sandbox'] });
const report = { checks: [], screens: [], errors: [], interceptedOrders: 0 };
const contexts = [];
async function login(page, role, path) {
  await page.goto(`${base}/anmelden?next=${encodeURIComponent(path)}`);
  await page.getByLabel('E-Mail-Adresse').fill(credentials[role]);
  await page.getByLabel('Passwort', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await page.waitForURL(`**${path}`);
  await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await page.getByRole('heading', { level: 1 }).waitFor();
}
async function newPage(width = 1440, height = 1000) {
  const context = await browser.newContext({ serviceWorkers: 'block', viewport: { width, height }, timezoneId: 'Europe/Berlin' });
  contexts.push(context);
  const page = await context.newPage();
  page.setDefaultTimeout(45000);
  page.on('pageerror', error => report.errors.push(error.message));
  page.on('response', response => {
    if (response.url().includes('/api/') && response.request().method() === 'GET' && response.status() >= 400) report.errors.push(`${response.status()} GET ${new URL(response.url()).pathname}`);
  });
  page.on('console', entry => {
    if (entry.type() === 'error' && !entry.text().includes('503') && !entry.text().includes('Failed to load resource')) report.errors.push(entry.text());
  });
  await context.route('**/*', async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== base || !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
      report.errors.push(`Blocked unproxied request: ${request.method()} ${url.pathname}`);
      await route.abort('blockedbyclient');
    } else await route.continue();
  });
  await context.route('**/api/**', async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method()) && !path.includes('/auth/') && !path.endsWith('/suggestions')) {
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Prüfung: Bestätigung absichtlich unterbrochen.' }) });
    } else if (socketPath) await fulfillFromIsolatedApi(route, socketPath);
    else await route.continue();
  });
  return page;
}
async function capture(page, name) {
  // Let finite background transitions settle before measuring their contrast.
  await page.evaluate(async () => { await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => undefined))); });
  const result = await new AxeBuilder({ page }).include('.fp').withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
  const smallTargets = await page.locator('.fp-icon, .fp-add, .fp-quantity button, .fp-cart-trigger').evaluateAll(elements => elements.filter(element => element.getClientRects().length).map(element => ({ label: element.getAttribute('aria-label') ?? element.textContent, width: element.getBoundingClientRect().width, height: element.getBoundingClientRect().height })).filter(item => item.width < 44 || item.height < 44));
  const violations = result.violations.map(item => ({ id: item.id, targets: item.nodes.map(node => node.target), detail: item.nodes.map(node => node.failureSummary) }));
  const screenshot = `${root}/${name}.png`;
  await page.screenshot({ path: screenshot, fullPage: page.viewportSize().width > 700 });
  report.screens.push({ name, viewport: page.viewportSize(), screenshot, overflow, smallTargets, violations });
}
try {
  const page = await newPage();
  await login(page, 'manager', '/gastro');
  await capture(page, 'manager-overview');
  for (const [label, heading, name] of [
    ['Lager & Waren', 'Was im Lager liegt.', 'manager-inventory'],
    ['Einkauf', 'Vom Lieferanten bis ins Lager.', 'manager-purchasing'],
    ['Produktion & Hygiene', 'Küche mit Überblick', 'manager-production'],
    ['Betriebsüberblick', 'Was läuft. Was Aufmerksamkeit braucht.', 'manager-insights'],
  ]) {
    await page.getByRole('button', { name: label, exact: true }).click();
    await page.getByRole('heading', { name: heading, exact: true }).waitFor();
    await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
    await capture(page, name);
  }
  await page.getByRole('navigation', { name: 'Betriebsnavigation' }).getByRole('button', { name: 'Bestellungen', exact: false }).click();
  await page.getByLabel('Tisch oder Aktivität').waitFor();
  const tables = await page.getByLabel('Tisch oder Aktivität').locator('option').evaluateAll(options => options.map(option => option.value).filter(Boolean));
  expect(tables.length).toBeGreaterThan(1);
  await page.getByLabel('Tisch oder Aktivität').selectOption(tables[0]);
  await page.locator('.fp-add:not(:disabled)').first().click();
  await page.getByLabel('Hinweis zur Bestellung', { exact: true }).fill('Prüfentwurf A · ohne Zwiebeln');
  await capture(page, 'manager-order-draft');
  await page.getByRole('button', { name: 'Küche & Bar', exact: true }).click();
  await capture(page, 'manager-kitchen');
  await page.getByRole('navigation', { name: 'Betriebsnavigation' }).getByRole('button', { name: 'Bestellungen', exact: false }).click();
  await expect(page.locator('.fp-cart-line')).toHaveCount(1);
  await expect(page.getByLabel('Hinweis zur Bestellung', { exact: true })).toHaveValue('Prüfentwurf A · ohne Zwiebeln');
  report.checks.push('Warenkorb und Notiz bleiben nach Bestellungen → Küche → Bestellungen erhalten.');
  await page.getByLabel('Tisch oder Aktivität').selectOption(tables[1]);
  await expect(page.locator('.fp-cart-line')).toHaveCount(0);
  await page.locator('.fp-add:not(:disabled)').first().click();
  await page.getByLabel('Hinweis zur Bestellung', { exact: true }).fill('Prüfentwurf B');
  await page.getByLabel('Tisch oder Aktivität').selectOption(tables[0]);
  await expect(page.getByLabel('Hinweis zur Bestellung', { exact: true })).toHaveValue('Prüfentwurf A · ohne Zwiebeln');
  report.checks.push('Tisch A und Tisch B besitzen getrennte Auswahl und Notiz.');
  // A read-only second-venue fixture exercises the actual venue selector without
  // provisioning or mutating another business. Authorization is a backend test.
  const secondVenue = '00000000-0000-4000-8000-000000000006';
  await page.route('**/api/gastro/venues', async route => {
    const response = socketPath ? await requestIsolatedApi(route.request(), socketPath) : await route.fetch();
    const venues = socketPath ? JSON.parse(response.body.toString('utf8')) : await response.json();
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([...venues, { ...venues[0], id: secondVenue, name: 'Prüfbetrieb Entwurftrennung' }]) });
  });
  await page.route(`**/api/gastro/venues/${secondVenue}/**`, async route => {
    if (route.request().method() !== 'GET') { await route.fallback(); return; }
    const url = route.request().url().replace(secondVenue, credentials.venue_id);
    if (socketPath) await fulfillFromIsolatedApi(route, socketPath, url);
    else { const response = await route.fetch({ url }); await route.fulfill({ response }); }
  });
  await page.reload();
  await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await page.getByRole('navigation', { name: 'Betriebsnavigation' }).getByRole('button', { name: 'Bestellungen', exact: false }).click();
  await page.getByLabel('Betriebsstätte wechseln').selectOption(secondVenue);
  await page.getByRole('navigation', { name: 'Betriebsnavigation' }).getByRole('button', { name: 'Bestellungen', exact: false }).click();
  await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await expect(page.locator('.fp-cart-line')).toHaveCount(0);
  await expect(page.getByLabel('Hinweis zur Bestellung', { exact: true })).toHaveValue('');
  await page.getByLabel('Betriebsstätte wechseln').selectOption(credentials.venue_id);
  await page.getByRole('navigation', { name: 'Betriebsnavigation' }).getByRole('button', { name: 'Bestellungen', exact: false }).click();
  await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await expect(page.getByLabel('Hinweis zur Bestellung', { exact: true })).toHaveValue('Prüfentwurf A · ohne Zwiebeln');
  report.checks.push('Betriebswechsel trennt Entwürfe (zweiter Betrieb als explizite reine Lesefixture).');
  const payloads = [];
  const orderRoute = `**/api/gastro/venues/${credentials.venue_id}/orders`;
  await page.route(orderRoute, async route => {
    if (route.request().method() !== 'POST') { await route.fallback(); return; }
    payloads.push(route.request().postDataJSON());
    report.interceptedOrders++;
    await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Prüfung: Antwort der Bestellung unterbrochen.' }) });
  });
  await page.getByRole('button', { name: 'An Küche & Bar senden', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Bestellung erneut prüfen', exact: true })).toBeEnabled();
  await page.reload();
  await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await page.getByRole('navigation', { name: 'Betriebsnavigation' }).getByRole('button', { name: 'Bestellungen', exact: false }).click();
  await expect(page.getByLabel('Tisch oder Aktivität')).toHaveValue(tables[0]);
  await expect(page.getByLabel('Hinweis zur Bestellung', { exact: true })).toHaveValue('Prüfentwurf A · ohne Zwiebeln');
  await expect(page.getByLabel('Hinweis zur Bestellung', { exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Bestellung erneut prüfen', exact: true }).click();
  await expect.poll(() => payloads.length).toBe(2);
  expect(payloads[1]).toEqual(payloads[0]);
  report.checks.push('503 + Reload + Retry erhält identische Vorgangs-ID und vollständigen Sendepayload; Änderungen bleiben gesperrt.');
  await page.setViewportSize({ width: 390, height: 844 });
  const trigger = page.getByRole('button', { name: /Warenkorb öffnen/ });
  await expect(trigger).toBeVisible();
  const box = await trigger.boundingBox();
  expect(box.y + box.height).toBeLessThanOrEqual(844);
  await page.locator('.fp-item').last().scrollIntoViewIfNeeded();
  await expect(trigger).toBeInViewport();
  await capture(page, 'manager-mobile');
  await trigger.click();
  await expect(page.getByRole('dialog', { name: 'Bestellung', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Bestellung erneut prüfen', exact: true })).toBeVisible();
  await capture(page, 'manager-mobile-cart');
  await page.keyboard.press('Escape');
  await expect(trigger).toBeFocused();
  await page.evaluate(() => { document.documentElement.style.zoom = '200%'; });
  await trigger.click();
  const zoomDialog = await page.getByRole('dialog', { name: 'Bestellung', exact: true }).boundingBox();
  expect(zoomDialog.y).toBeGreaterThanOrEqual(0);
  expect(zoomDialog.y + zoomDialog.height).toBeLessThanOrEqual(844);
  const zoomDescription = await page.locator('.fp-cart-line > div:first-child').boundingBox();
  expect(zoomDescription.width).toBeGreaterThanOrEqual(100);
  await page.getByRole('dialog').getByRole('button', { name: 'Bestellung erneut prüfen', exact: true }).scrollIntoViewIfNeeded();
  await capture(page, 'manager-mobile-cart-zoom200');
  await page.keyboard.press('Escape');
  await page.evaluate(() => { document.documentElement.style.zoom = ''; });
  report.checks.push('Mobile Warenkorb-CTA, Dialog, Escape/Fokusrückkehr und 200-%-Zoom geprüft.');
  await page.getByRole('button', { name: 'Abmelden', exact: true }).filter({ visible: true }).click();
  await page.waitForURL('**/anmelden');
  const privateKeys = await page.evaluate(() => Object.keys(localStorage).filter(key => key.startsWith('flintplate:') && (key.includes('order-draft:') || key.includes('-pending:'))));
  expect(privateKeys).toEqual([]);
  await login(page, 'worker', '/gastro');
  await page.getByRole('navigation', { name: 'Betriebsnavigation' }).getByRole('button', { name: 'Bestellungen', exact: false }).click();
  await page.getByRole('button', { name: /Warenkorb öffnen/ }).click();
  await expect(page.locator('.fp-cart-line')).toHaveCount(0);
  await expect(page.getByLabel('Hinweis zur Bestellung', { exact: true })).toHaveValue('');
  report.checks.push('Logout löscht sämtliche private Draftkeys; nachfolgender Servicenutzer sieht leeren Entwurf.');
  for (const [role, destination] of [['worker', '/team'], ['guest', `/kunden/${credentials.venue_id}`]]) {
    const rolePage = await newPage(390, 844);
    await login(rolePage, role, destination);
    await capture(rolePage, `${role}-mobile`);
  }
  expect(report.errors).toEqual([]);
  expect(report.screens.flatMap(screen => screen.violations)).toEqual([]);
  expect(report.screens.filter(screen => screen.overflow)).toEqual([]);
  expect(report.screens.flatMap(screen => screen.smallTargets)).toEqual([]);
} catch (error) {
  report.failed = String(error);
  process.exitCode = 1;
} finally {
  await Promise.all(contexts.map(context => context.close()));
  await browser.close();
  await fs.writeFile(`${root}/report.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
}
