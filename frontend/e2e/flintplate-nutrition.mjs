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
await call(manager, `/gastro/venues/${venue}/diet-markers/defaults`, 'POST').catch(() => null);

// A dish with alcohol, so the legal block has something to bite on.
const sku = `D-WEIN-${Math.random().toString(36).slice(2, 5).toUpperCase()}`;
const wine = await call(manager, `/gastro/venues/${venue}/menu`, 'POST', {
  sku,
  data: {
    name: `Hauswein ${sku.slice(-3)}`, description: 'Trocken, aus der Region.', category: 'Getränke',
    price_cents: 590, tax_rate_bps: 1900, cost_cents: 150, allergens: ['Sulfite'], available: true,
    station: 'bar', contains: ['alkohol'],
    ingredients: [{ name: 'Weißwein', allergens: ['Sulfite'], note: 'Riesling' }, { name: 'Schwefel', allergens: [], note: 'als Konservierung' }],
  },
});
await call(manager, `/gastro/venues/${venue}/menu/${wine.id}/publish`, 'POST', { version: 1 });
report.dish = wine.sku;

const browser = await chromium.launch({ executablePath: '/tmp/palmscout-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell', headless: true, args: ['--disable-gpu', '--disable-dev-shm-usage', '--no-sandbox'] });
const errors = [];
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, timezoneId: 'Europe/Berlin' });
  const page = await context.newPage();
  page.setDefaultTimeout(120000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', item => { if (item.type() === 'error') errors.push(item.text()); });
  page.on('dialog', dialog => void dialog.accept());

  await page.goto('http://localhost:3012/anmelden?next=%2Fgastro', { timeout: 180000 });
  await page.getByLabel('E-Mail-Adresse').fill(credentials.manager);
  await page.getByLabel('Passwort', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await page.waitForURL('**/gastro', { timeout: 180000 });
  await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });

  // 1. Der Kellner ruft die Zutaten am Bestellschirm auf.
  await page.getByRole('button', { name: 'Bestellungen' }).click();
  await page.getByLabel(`Zutaten von Hauswein ${sku.slice(-3)}`).click();
  await page.getByRole('heading', { name: `Hauswein ${sku.slice(-3)}` }).waitFor();
  report.ingredients = await page.locator('.fp-ingredients li').allInnerTexts();
  report.labelling = await page.locator('.fp-hint').last().innerText();
  await page.screenshot({ path: `${root}/nutrition-dish.png` });
  await page.getByRole('button', { name: 'Schließen' }).click().catch(() => page.keyboard.press('Escape'));

  // 2. Merkmale sind gepflegt und zeigen die gesetzliche Sperre.
  await page.getByRole('button', { name: 'Gäste & Vorteile' }).click();
  const markers = page.locator('.fp-marker');
  await markers.first().waitFor();
  report.markers = await markers.allInnerTexts();
  await page.screenshot({ path: `${root}/nutrition-markers.png`, fullPage: true });

  // 3. Ein Gast bekommt ein Merkmal, das eine Einwilligung braucht.
  const person = `Testgast ${Math.random().toString(36).slice(2, 6)}`;
  await page.getByRole('button', { name: 'Gast aufnehmen' }).click();
  await page.getByLabel('Name oder Ansprache').fill(person);
  await page.getByRole('button', { name: 'Aufnehmen', exact: true }).click();
  await page.locator('.fp-guest-card').filter({ hasText: person }).click();
  await page.getByRole('heading', { name: person }).waitFor();
  await page.getByRole('button', { name: /Minderjährig/ }).click();
  const refusal = page.locator('.fp-notice.error');
  await refusal.waitFor();
  report.refusal = await refusal.innerText();

  await page.getByRole('button', { name: 'Einwilligung festhalten' }).click();
  await page.getByRole('status').filter({ hasText: 'Einwilligung festgehalten' }).waitFor();
  await page.getByRole('button', { name: /Minderjährig/ }).click();
  await page.getByRole('status').filter({ hasText: 'Merkmale gespeichert' }).waitFor();
  report.marker_set = await page.getByRole('button', { name: /Minderjährig/ }).getAttribute('aria-pressed');
  await page.screenshot({ path: `${root}/nutrition-guest.png`, fullPage: true });

  report.overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  await context.close();
} catch (error) {
  report.failed = String(error).split('\n')[0];
} finally {
  await browser.close();
  report.errors = errors;
  await fs.writeFile(`${root}/nutrition.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
}
