import { chromium } from '@playwright/test';
import fs from 'node:fs/promises';

const credentials = JSON.parse(await fs.readFile(new URL('../../backend/.local/demo-access.json', import.meta.url), 'utf8'));
const root = '/tmp/hireos-browser-tests/flintplate';
const API = 'http://localhost:3012/api';
const venue = credentials.venue_id;
await fs.mkdir(root, { recursive: true });
const report = {};

async function login(email) {
  const response = await fetch(`${API}/auth/login`, {
    method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: email, password: credentials.password }),
  });
  return (await response.json()).access_token;
}
async function call(token, path, method = 'GET', payload) {
  const response = await fetch(`${API}${path}`, {
    method, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const text = await response.text();
  if (!response.ok) throw new Error(`${method} ${path} → ${response.status}: ${text.slice(0, 200)}`);
  return text ? JSON.parse(text) : null;
}

const manager = await login(credentials.manager);
const tag = Math.random().toString(36).slice(2, 5).toUpperCase();
const made = {};
for (const [sku, name, category] of [[`S-SUP-${tag}`, `Kürbissuppe ${tag}`, 'Speisen'], [`D-WEI-${tag}`, `Weißwein ${tag}`, 'Getränke']]) {
  const item = await call(manager, `/gastro/venues/${venue}/menu`, 'POST', {
    sku,
    data: { name, description: 'Für den Vorschlagstest.', category, price_cents: 690, tax_rate_bps: 1900, cost_cents: 200, allergens: [], available: true, station: category === 'Getränke' ? 'bar' : 'kitchen', contains: [] },
  });
  await call(manager, `/gastro/venues/${venue}/menu/${item.id}/publish`, 'POST', { version: 1 });
  made[sku] = item;
}
const tables = await call(manager, `/gastro/venues/${venue}/tables`);
for (let index = 0; index < 3; index += 1) {
  await call(manager, `/gastro/venues/${venue}/orders`, 'POST', {
    request_key: crypto.randomUUID(),
    table_id: tables[0].id,
    lines: Object.values(made).map(item => ({ item_id: item.id, menu_version: 1, quantity: 1 })),
  });
}
report.history = 'drei Bestellungen mit beiden Artikeln';

const browser = await chromium.launch({ executablePath: '/tmp/palmscout-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell', headless: true, args: ['--disable-gpu', '--disable-dev-shm-usage', '--no-sandbox'] });
const errors = [];
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, timezoneId: 'Europe/Berlin' });
  const page = await context.newPage();
  page.setDefaultTimeout(120000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', item => { if (item.type() === 'error') errors.push(item.text()); });

  await page.goto('http://localhost:3012/anmelden?next=%2Fgastro', { timeout: 180000 });
  await page.getByLabel('E-Mail-Adresse').fill(credentials.manager);
  await page.getByLabel('Passwort', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await page.waitForURL('**/gastro', { timeout: 180000 });
  await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await page.getByRole('button', { name: 'Bestellungen' }).click();

  await page.getByLabel(`Kürbissuppe ${tag} hinzufügen`).click();
  const suggest = page.locator('.fp-suggest');
  await suggest.waitFor();
  report.suggestion = await suggest.innerText();

  // One tap adds the suggested item to the cart.
  const before = await page.locator('.fp-cart-line').count();
  await page.locator('.fp-suggest-row').first().click();
  await page.waitForFunction(count => document.querySelectorAll('.fp-cart-line').length > count, before);
  report.cart = await page.locator('.fp-cart-line strong').allInnerTexts();
  await page.screenshot({ path: `${root}/suggestions.png`, fullPage: true });

  report.overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  await context.close();
} catch (error) {
  report.failed = String(error).split('\n')[0];
} finally {
  await browser.close();
  report.errors = errors;
  await fs.writeFile(`${root}/suggestions.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
}
