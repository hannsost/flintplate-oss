import { chromium, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs/promises';
import { fulfillFromIsolatedApi } from './flintplate-browser-api.mjs';

const socket = process.env.FLINTPLATE_BROWSER_SOCKET;
if (!socket) throw new Error('Only the isolated browser acceptance API is allowed.');
const credentials = JSON.parse(await fs.readFile(process.env.FLINTPLATE_BROWSER_CREDENTIALS, 'utf8'));
const output = '/tmp/hireos-browser-tests/flintplate-mobile-followup';
await fs.mkdir(output, { recursive: true });
const report = { readOnly: true, screenshots: [], checks: [], errors: [] };
const browser = await chromium.launch({ executablePath: '/tmp/palmscout-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell', headless: true, args: ['--disable-gpu', '--disable-dev-shm-usage', '--no-sandbox'] });
const context = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 1440, height: 1050 }, timezoneId: 'Europe/Berlin' });
const page = await context.newPage();
page.setDefaultTimeout(30000);
page.on('pageerror', error => report.errors.push(error.message));
page.on('response', response => { if (response.url().includes('/api/') && response.request().method() === 'GET' && response.status() >= 400) report.errors.push(`${response.status()} GET ${new URL(response.url()).pathname}`); });
await context.route('**/*', async route => {
  const request = route.request(), url = new URL(request.url());
  if (url.origin !== 'http://localhost:3012' || !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) { report.errors.push(`Blocked unproxied request: ${request.method()} ${url.pathname}`); await route.abort('blockedbyclient'); }
  else await route.continue();
});
await context.route('**/api/**', async route => {
  const request = route.request(), path = new URL(request.url()).pathname;
  if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method()) && !path.includes('/auth/')) { report.errors.push(`Blocked business write: ${request.method()} ${path}`); await route.abort('blockedbyclient'); }
  else await fulfillFromIsolatedApi(route, socket);
});
const card = name => page.locator('article').filter({ has: page.getByRole('heading', { name, exact: true }) });
async function nav(name) { await page.getByRole('navigation', { name: 'Betriebsnavigation' }).getByRole('button', { name, exact: false }).click(); await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' }); }
async function shot(name) {
  await page.evaluate(async () => { await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => undefined))); });
  const axe = await new AxeBuilder({ page }).include('.fp').withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
  const path = `${output}/${name}.png`; await page.screenshot({ path, fullPage: false });
  report.screenshots.push({ path, viewport: page.viewportSize(), overflow, violations: axe.violations.map(item => ({ id: item.id, targets: item.nodes.map(node => node.target) })) });
  expect(overflow).toBe(false); expect(axe.violations).toEqual([]);
}
try {
  await page.goto('http://localhost:3012/anmelden?next=%2Fgastro');
  await page.getByLabel('E-Mail-Adresse').fill(credentials.manager); await page.getByLabel('Passwort', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click(); await page.waitForURL('**/gastro'); await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await nav('Produktion & Hygiene'); await page.getByRole('button', { name: 'Kontrollpläne', exact: true }).click();
  await expect(card('Browser Kühlplan')).toBeVisible(); await shot('kontrollplan-desktop-nach-kopfkorrektur');
  await page.setViewportSize({ width: 390, height: 844 }); await page.evaluate(() => scrollTo(0, 0));
  const task = card('Browser Kühlplan'), control = task.getByRole('button', { name: 'Kontrolle erfassen', exact: true });
  const bounds = await control.boundingBox(); expect(bounds).not.toBeNull(); expect(bounds.y).toBeGreaterThanOrEqual(0); expect(bounds.y + bounds.height).toBeLessThanOrEqual(844); expect(bounds.height).toBeGreaterThanOrEqual(44);
  await shot('kontrollplan-mobil-erste-aufgabe-ohne-scrollen');
  report.checks.push(`390×844: erste fällige Kontrolle und ihre 44px Aktion ohne Scrollen erreichbar (Aktion y=${Math.round(bounds.y)}).`);
  await page.setViewportSize({ width: 320, height: 844 }); await page.evaluate(() => scrollTo(0, 0)); await expect(task).toBeVisible();
  const smallBounds = await task.boundingBox(); expect(smallBounds.y).toBeLessThan(744); await shot('kontrollplan-mobil-320');
  await page.setViewportSize({ width: 1440, height: 1050 }); await page.getByRole('button', { name: 'Rezepturen', exact: true }).click(); await page.getByRole('button', { name: 'Rezeptur anlegen', exact: true }).click();
  const dialog = page.getByRole('dialog'); await expect(dialog.getByLabel('Gericht auf der Karte (optional)')).toHaveAttribute('aria-describedby', 'fp-recipe-portions'); await expect(dialog.getByText('Für ein Gericht auf der Karte muss der Ausgabeartikel in Stück geführt werden:', { exact: false })).toBeVisible(); await shot('rezept-portionenhinweis'); await dialog.getByRole('button', { name: 'Dialog schließen', exact: true }).click();
  report.checks.push('Kartenbindung erklärt Stück pro Portion und interne kg/l-Unterrezepte direkt am zugehörigen Feld.');
  await nav('Reservierungen'); await page.getByRole('button', { name: /^Erledigt/ }).click();
  await page.setViewportSize({ width: 390, height: 844 }); await expect(card('Browser Tischgruppe')).toBeVisible(); await card('Browser Tischgruppe').scrollIntoViewIfNeeded(); await shot('gruppenreservierung-mobil-karte');
  report.checks.push('Abgeschlossene Tischgruppe in mobiler Kartenansicht gelesen; keine Geschäftsdaten verändert.');
  expect(report.errors).toEqual([]);
} catch (error) { report.failure = error.stack; const path = `${output}/failure.png`; await page.screenshot({ path, fullPage: true }).catch(() => undefined); report.screenshots.push({ path }); }
finally { await fs.writeFile(`${output}/report.json`, JSON.stringify(report, null, 2)); await browser.close(); }
console.log(JSON.stringify(report, null, 2));
if (report.failure) process.exitCode = 1;
