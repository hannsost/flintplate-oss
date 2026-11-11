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
const browser = await chromium.launch({ executablePath: '/tmp/palmscout-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell', headless: true, args: ['--disable-gpu', '--disable-dev-shm-usage', '--no-sandbox'] });
const errors = [];
try {
  // Guest orders on the phone and never touches a refresh button again.
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, timezoneId: 'Europe/Berlin' });
  const guest = await phone.newPage();
  guest.setDefaultTimeout(120000);
  guest.on('pageerror', error => errors.push(error.message));
  guest.on('console', item => { if (item.type() === 'error') errors.push(item.text()); });
  await guest.goto(`http://localhost:3012/anmelden?next=${encodeURIComponent(`/kunden/${venue}`)}`, { timeout: 180000 });
  await guest.getByLabel('E-Mail-Adresse').fill(credentials.guest);
  await guest.getByLabel('Passwort', { exact: true }).fill(credentials.password);
  await guest.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await guest.waitForURL(`**/kunden/${venue}`, { timeout: 180000 });
  await guest.getByRole('button', { name: 'Vor Ort' }).click();
  await guest.getByLabel('Dein Tisch').selectOption({ index: 1 });
  await guest.locator('.fp-add').first().click();
  await guest.getByRole('button', { name: 'An den Tisch bestellen' }).click();
  await guest.getByRole('status').filter({ hasText: 'ist eingegangen' }).waitFor();
  await guest.getByRole('button', { name: 'Mein Besuch' }).click();

  const card = guest.locator('.fp-guest-order').first();
  await card.waitFor();
  report.steps = await card.locator('.fp-steps li').allInnerTexts();
  report.current_step = await card.locator('.fp-steps li.current').innerText();
  report.can_take_back = await card.getByRole('button', { name: 'Bestellung zurücknehmen' }).isVisible();
  await guest.screenshot({ path: `${root}/live-guest-progress.png`, fullPage: true });

  // The kitchen starts; the phone must notice on its own.
  const orders = await call(manager, `/gastro/venues/${venue}/orders`);
  let order = orders.find(row => row.status === 'sent');
  order = await call(manager, `/gastro/venues/${venue}/orders/${order.id}/status`, 'POST', { version: order.version, status: 'preparing' });
  const started = Date.now();
  await card.locator('.fp-steps li.current', { hasText: 'Wird zubereitet' }).waitFor({ timeout: 60000 });
  report.live_update_seconds = Math.round((Date.now() - started) / 1000);

  // Operations: attention strip, kitchen timer, table state.
  const desk = await browser.newContext({ viewport: { width: 1440, height: 1100 }, timezoneId: 'Europe/Berlin' });
  const office = await desk.newPage();
  office.setDefaultTimeout(120000);
  office.on('pageerror', error => errors.push(error.message));
  office.on('console', item => { if (item.type() === 'error') errors.push(item.text()); });
  await office.goto('http://localhost:3012/anmelden?next=%2Fgastro', { timeout: 180000 });
  await office.getByLabel('E-Mail-Adresse').fill(credentials.manager);
  await office.getByLabel('Passwort', { exact: true }).fill(credentials.password);
  await office.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await office.waitForURL('**/gastro', { timeout: 180000 });
  await office.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });

  order = await call(manager, `/gastro/venues/${venue}/orders/${order.id}/status`, 'POST', { version: order.version, status: 'ready' });
  order = await call(manager, `/gastro/venues/${venue}/orders/${order.id}/status`, 'POST', { version: order.version, status: 'served' });
  await call(manager, `/gastro/venues/${venue}/orders/${order.id}/checkout`, 'POST', { version: order.version });
  await office.reload();
  await office.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  const strip = office.locator('.fp-attention');
  await strip.waitFor();
  report.attention = await strip.innerText();
  await office.screenshot({ path: `${root}/live-attention.png`, fullPage: true });

  await office.getByRole('button', { name: 'Räume & Aktivitäten' }).click();
  await office.getByLabel('Stockwerk').selectOption('');
  const marked = office.locator('.fp-resource.bill').first();
  report.table_state = await marked.innerText({ timeout: 20000 }).catch(() => 'kein Tisch mit angeforderter Zahlung sichtbar');
  report.table_states = await office.locator('.fp-resource-state').allInnerTexts();
  await office.screenshot({ path: `${root}/live-floorplan.png`, fullPage: true });

  await office.getByRole('button', { name: 'Küche & Bar' }).click();
  const ticket = office.locator('.fp-kitchen-ticket .fp-elapsed').first();
  report.kitchen_timer = (await ticket.count()) ? await ticket.innerText() : 'keine offenen Tickets';
  report.overflow = await office.evaluate(() => document.documentElement.scrollWidth > innerWidth);

  report.errors = errors;
  await desk.close();
  await phone.close();
} catch (error) {
  report.failed = String(error).split('\n')[0];
} finally {
  await browser.close();
  report.errors = errors;
  await fs.writeFile(`${root}/live-ux.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
}
