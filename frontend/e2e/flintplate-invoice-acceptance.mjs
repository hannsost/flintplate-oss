import { chromium, expect } from '@playwright/test';
import fs from 'node:fs/promises';
import { fulfillFromIsolatedApi } from './flintplate-browser-api.mjs';

// Continues the invoice stage on the isolated fixture created by the ERP test.
const socket = process.env.FLINTPLATE_BROWSER_SOCKET;
if (!socket) throw new Error('The isolated API socket is required.');
const credentials = JSON.parse(await fs.readFile(process.env.FLINTPLATE_BROWSER_CREDENTIALS ?? new URL('../../backend/.local/browser-acceptance-access.json', import.meta.url), 'utf8'));
const output = '/tmp/hireos-browser-tests/flintplate-invoice-acceptance';
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH ?? '/tmp/palmscout-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell', headless: true, args: ['--disable-gpu', '--disable-dev-shm-usage', '--no-sandbox'] });
const context = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 1440, height: 1050 }, timezoneId: 'Europe/Berlin' });
const page = await context.newPage();
page.setDefaultTimeout(30000);
const report = { isolated: true, checks: [], screenshots: [], errors: [], writes: [] };
page.on('pageerror', error => report.errors.push(error.message));
await context.route('**/*', route => new URL(route.request().url()).origin === 'http://localhost:3012' && ['GET', 'HEAD', 'OPTIONS'].includes(route.request().method()) ? route.continue() : route.abort('blockedbyclient'));
await context.route('**/api/**', route => fulfillFromIsolatedApi(route, socket));
async function shot(name) {
  const path = `${output}/${name}.png`;
  await page.screenshot({ path, fullPage: true });
  report.screenshots.push(path);
}
async function post(button, suffix) {
  const response = page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith(suffix));
  await button.click();
  const result = await response;
  const json = await result.json();
  report.writes.push({ path: new URL(result.url()).pathname, status: result.status() });
  expect(result.ok(), JSON.stringify(json)).toBe(true);
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Bestellung', exact: true })).toBeEnabled();
  return json;
}
try {
  await page.goto('http://localhost:3012/anmelden?next=%2Fgastro');
  await page.getByLabel('E-Mail-Adresse').fill(credentials.manager);
  await page.getByLabel('Passwort', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await page.waitForURL('**/gastro');
  await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await page.getByRole('navigation', { name: 'Betriebsnavigation' }).getByRole('button', { name: 'Einkauf', exact: true }).click();
  await page.getByRole('heading', { name: 'Vom Lieferanten bis ins Lager.', exact: true }).waitFor();
  const purchaseCard = page.locator('section.fp-panel').filter({ has: page.getByRole('heading', { name: 'EK-1001 · Browserlieferant', exact: true }) });
  await expect(purchaseCard.locator('summary')).toHaveText('Wareneingänge (1)');
  for (const [net, matched] of [['6', false], ['5', true]]) {
    await page.getByRole('group', { name: 'Einkaufsansicht' }).getByRole('button', { name: 'Bestellungen', exact: true }).click();
    await purchaseCard.getByRole('button', { name: 'Rechnung erfassen', exact: true }).click();
    await page.getByLabel('Rechnungsnummer').fill('RE-BROWSER');
    await page.getByRole('dialog').getByRole('checkbox', { name: 'EK-1001 · Basiszutat', exact: true }).check();
    await page.getByLabel('Berechnete Menge in kg').fill('2.5');
    await page.getByLabel('Berechneter Nettobetrag in €').fill(net);
    const invoice = await post(page.getByRole('button', { name: 'Rechnung erfassen und vergleichen', exact: true }), '/invoices');
    expect(invoice.check.matched).toBe(matched);
    await page.getByRole('button', { name: 'Rechnungsprüfung', exact: true }).click();
    const card = page.locator('section.fp-panel').filter({ has: page.getByRole('heading', { name: 'RE-BROWSER · Browserlieferant', exact: true }) }).filter({ has: page.getByRole('button', { name: 'Fachlich freigeben', exact: true }) });
    if (matched) await card.getByRole('button', { name: 'Fachlich freigeben', exact: true }).click();
    else {
      await expect(card.getByRole('button', { name: 'Fachlich freigeben', exact: true })).toBeDisabled();
      await shot('rechnungsdifferenz-gesperrt');
      await card.getByRole('button', { name: 'Zurückweisen', exact: true }).click();
    }
    await page.getByLabel('Begründung / Notiz').fill(matched ? 'Korrigierter Preis und Teilmenge stimmen' : 'Nettopreis weicht vom bestellten Gebinde ab');
    await post(page.getByRole('dialog').getByRole('button', { name: 'Bestätigen', exact: true }), '/decision');
  }
  await expect(page.getByText('Fachlich freigegeben', { exact: true })).toBeVisible();
  await shot('rechnung-korrigiert-freigegeben');
  await page.getByRole('navigation', { name: 'Betriebsnavigation' }).getByRole('button', { name: 'Lager & Waren', exact: true }).click();
  await expect(page.getByRole('row').filter({ hasText: 'PURCHASE-BROWSER' })).toContainText('2,5 kg');
  report.checks.push('Teilannahme bleibt genau einmal vorhanden. Rechnungsdifferenz blockiert fachliche Freigabe; nach Zurückweisung kann dieselbe Rechnungsnummer korrigiert freigegeben werden. Lagerzugang exakt 2,5 kg.');
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
