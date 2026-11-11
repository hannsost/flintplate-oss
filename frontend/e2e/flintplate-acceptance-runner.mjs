import { chromium, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs/promises';
import { fulfillFromIsolatedApi, requestIsolatedApi } from './flintplate-browser-api.mjs';

export function acceptanceBaseUrl(value = process.env.FLINTPLATE_BROWSER_BASE_URL ?? 'http://localhost:3012') {
  if (!/^http:\/\/(localhost|127\.0\.0\.1|192\.168\.0\.160):301[28]\/?$/.test(value)) throw new Error('FLINTPLATE_BROWSER_BASE_URL must be http://localhost:3012, http://localhost:3018 or the corresponding 127.0.0.1 / local192.168.0.160 origin.');
  return new URL(value).origin;
}

// Every business mutation must pass through visible UI controls and the isolated
// Unix-socket API. No request can fall back to the local business database.
export async function acceptance(name) {
  const baseUrl = acceptanceBaseUrl();
  const socket = process.env.FLINTPLATE_BROWSER_SOCKET;
  if (!socket) throw new Error('FLINTPLATE_BROWSER_SOCKET is required; business writes are forbidden.');
  const credentials = JSON.parse(await fs.readFile(process.env.FLINTPLATE_BROWSER_CREDENTIALS, 'utf8'));
  const output = `/tmp/hireos-browser-tests/${name}`;
  await fs.mkdir(output, { recursive: true });
  const browser = await chromium.launch({ executablePath: '/tmp/palmscout-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell', headless: true, args: ['--disable-gpu', '--disable-dev-shm-usage', '--no-sandbox'] });
  const context = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 1440, height: 1050 }, timezoneId: 'Europe/Berlin' });
  const page = await context.newPage(); page.setDefaultTimeout(30000);
  const report = { baseUrl, checks: [], writes: [], networkWrites: [], screenshots: [], errors: [] };
  page.on('request', request => { const url = new URL(request.url()); if (url.pathname.startsWith('/api/gastro/') && !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) report.networkWrites.push({ path: url.pathname, method: request.method() }); });
  page.on('pageerror', error => report.errors.push(error.message));
  page.on('response', response => { if (response.url().includes('/api/') && response.request().method() === 'GET' && response.status() >= 400) report.errors.push(`${response.status()} GET ${new URL(response.url()).pathname}`); });
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== baseUrl || !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) { report.errors.push(`Blocked unproxied request: ${request.method()} ${url.pathname}`); await route.abort('blockedbyclient'); }
    else await route.continue();
  });
  await context.route('**/api/**', async route => {
    if (new URL(route.request().url()).origin !== baseUrl) { report.errors.push('Blocked API request outside the selected UI origin.'); await route.abort('blockedbyclient'); return; }
    await fulfillFromIsolatedApi(route, socket);
  });
  const modal = () => page.getByRole('dialog');
  async function login(role = 'manager') { await page.goto(`${baseUrl}/anmelden?next=%2Fgastro`); await page.getByLabel('E-Mail-Adresse').fill(credentials[role]); await page.getByLabel('Passwort', { exact: true }).fill(credentials.password); await page.getByRole('button', { name: 'Anmelden', exact: true }).click(); await page.waitForURL(`${baseUrl}/gastro`); await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' }); }
  async function nav(name) { await page.getByRole('navigation', { name: 'Betriebsnavigation' }).getByRole('button', { name, exact: false }).click(); await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' }); }
  async function write(click, suffix, status = 201, method = 'POST') { const [response] = await Promise.all([page.waitForResponse(response => response.request().method() === method && new URL(response.url()).pathname.endsWith(suffix)), click()]); const result = await response.json(); report.writes.push({ path: new URL(response.url()).pathname, status: response.status(), method }); console.log(JSON.stringify({ checkpoint: suffix, status: response.status() })); expect(response.status(), JSON.stringify(result)).toBe(status); return result; }
  async function submit(label, suffix, status = 201, method = 'POST') { const result = await write(() => modal().getByRole('button', { name: label, exact: true }).click(), suffix, status, method); if (status < 300) await expect(modal()).toHaveCount(0); return result; }
  async function readOnNav(name, suffix) { const [response] = await Promise.all([page.waitForResponse(response => response.request().method() === 'GET' && new URL(response.url()).pathname.endsWith(suffix)), nav(name)]); expect(response.status()).toBe(200); return response.json(); }
  async function loseFirstAnswer(pattern, intermediateConflict = false) {
    const payloads = [];
    await page.route(pattern, async route => {
      if (new URL(route.request().url()).origin !== baseUrl) { report.errors.push('Blocked retry outside the selected UI origin.'); await route.abort('blockedbyclient'); return; }
      if (!['POST', 'PUT'].includes(route.request().method())) { await route.fallback(); return; }
      payloads.push(route.request().postDataJSON());
      if (intermediateConflict && payloads.length === 2) { await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'Isolierte Prüfung: nach unklarer Antwort vorübergehender Konflikt.' }) }); return; }
      const response = await requestIsolatedApi(route.request(), socket);
      if (payloads.length === 1) { expect(response.status).toBeGreaterThanOrEqual(200); expect(response.status).toBeLessThan(300); await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Isolierte Prüfung: gespeichert, erste Antwort gezielt verloren.' }) }); }
      else await route.fulfill(response);
    });
    return payloads;
  }
  async function shot(name) {
    await page.evaluate(async () => { await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => undefined))); });
    const axe = await new AxeBuilder({ page }).include('.fp').withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
    const path = `${output}/${name}.png`; await page.screenshot({ path, fullPage: page.viewportSize().width > 700 }); report.screenshots.push({ path, viewport: page.viewportSize(), overflow, violations: axe.violations.map(item => ({ id: item.id, targets: item.nodes.map(node => node.target) })) }); expect(overflow).toBe(false); expect(axe.violations).toEqual([]);
  }
  async function finish(error) { if (error) { report.failure = error.stack; const path = `${output}/failure.png`; await page.screenshot({ path, fullPage: true }).catch(() => undefined); report.screenshots.push({ path }); } else if (report.errors.length) report.failure = 'Browser diagnostics reported errors.'; await fs.writeFile(`${output}/report.json`, JSON.stringify(report, null, 2)); await browser.close(); console.log(JSON.stringify(report, null, 2)); if (report.failure) process.exitCode = 1; }
  return { page, context, credentials, report, output, modal, login, nav, write, submit, readOnNav, loseFirstAnswer, shot, finish };
}
export { expect };
