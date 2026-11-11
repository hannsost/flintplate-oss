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
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ username: email, password: credentials.password }),
  });
  if (!response.ok) throw new Error(`login ${email}: ${response.status}`);
  return (await response.json()).access_token;
}

async function call(token, path, method = 'GET', payload) {
  const response = await fetch(`${API}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const text = await response.text();
  if (!response.ok) throw new Error(`${method} ${path} → ${response.status}: ${text.slice(0, 300)}`);
  return text ? JSON.parse(text) : null;
}

const manager = await login(credentials.manager);
const worker = await login(credentials.worker);
const iso = date => date.toISOString();
const now = new Date();
const shiftEnd = new Date(now.getTime() - 60 * 60 * 1000);
const shiftStart = new Date(shiftEnd.getTime() - 4 * 60 * 60 * 1000);

// Someone has to have worked for a pot to be divisible.
const members = await call(manager, `/gastro/venues/${venue}/members`);
const staff = members.find(m => m.role === 'service' && m.active) || members[0];
const shift = await call(manager, `/gastro/venues/${venue}/shifts`, 'POST', {
  worker_id: staff.user_id, station: 'Service', starts_at: iso(shiftStart), ends_at: iso(shiftEnd), break_minutes: 0,
});
await call(manager, `/gastro/venues/${venue}/shifts/${shift.id}/status`, 'POST', { version: shift.version, status: 'published' });
const entry = await call(worker, '/worker/time', 'POST', { clock_in: iso(shiftStart) });
await call(worker, `/worker/time/${entry.id}`, 'PATCH', { clock_out: iso(shiftEnd), break_minutes: 0 });
report.prepared = { worker: staff.full_name, minutes: 240 };

const browser = await chromium.launch({ executablePath: '/tmp/palmscout-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell', headless: true, args: ['--disable-gpu', '--disable-dev-shm-usage', '--no-sandbox'] });
const errors = [];
const watch = page => {
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', item => { if (item.type() === 'error') errors.push(item.text()); });
};
async function signIn(page, email, destination) {
  await page.goto(`http://localhost:3012/anmelden?next=${encodeURIComponent(destination)}`, { timeout: 180000 });
  await page.getByLabel('E-Mail-Adresse').fill(email);
  await page.getByLabel('Passwort', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await page.waitForURL(`**${destination}`, { timeout: 180000 });
}

try {
  // 1. Betriebsleitung öffnet Tischbestellung und wählt die Trinkgeldregel.
  const desk = await browser.newContext({ viewport: { width: 1440, height: 1100 }, timezoneId: 'Europe/Berlin' });
  const office = await desk.newPage();
  office.setDefaultTimeout(120000);
  watch(office);
  await signIn(office, credentials.manager, '/gastro');
  await office.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await office.getByRole('button', { name: 'Anbindungen & Service' }).click();
  await office.getByRole('checkbox', { name: 'Gäste dürfen an den Tisch bestellen' }).check();
  await office.getByRole('checkbox', { name: 'Auch ohne eigene Reservierung am Tisch' }).check();
  await office.getByLabel('Trinkgeld verteilen').selectOption('pool_hours');
  await office.getByLabel('Küchenanteil am Topf in %').fill('0');
  await office.getByRole('button', { name: 'Einstellungen speichern' }).click();
  await office.getByRole('status').filter({ hasText: 'Kunden-App gespeichert' }).waitFor();
  report.settings_saved = true;

  // 2. Gast bestellt vom Handy an den Tisch.
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, timezoneId: 'Europe/Berlin' });
  const guest = await phone.newPage();
  guest.setDefaultTimeout(120000);
  watch(guest);
  await signIn(guest, credentials.guest, `/kunden/${venue}`);
  await guest.getByRole('button', { name: 'Vor Ort' }).click();
  const table = guest.getByLabel('Dein Tisch');
  await table.waitFor();
  const options = await table.locator('option').allTextContents();
  report.tables_offered = options.filter(Boolean).length - 1;
  await table.selectOption({ index: 1 });
  await guest.locator('.fp-add').first().click();
  await guest.getByRole('button', { name: 'An den Tisch bestellen' }).click();
  await guest.getByRole('status').filter({ hasText: 'ist eingegangen' }).waitFor();
  await guest.screenshot({ path: `${root}/tip-guest-order.png`, fullPage: true });

  // 3. Der Betrieb serviert.
  const orders = await call(manager, `/gastro/venues/${venue}/orders`);
  let order = orders.find(row => row.status === 'sent' && row.fulfillment === 'dine_in');
  report.order = { number: order.number, table: order.table_id !== null, total_cents: order.total_cents };
  for (const status of ['preparing', 'ready', 'served']) {
    order = await call(manager, `/gastro/venues/${venue}/orders/${order.id}/status`, 'POST', { version: order.version, status });
  }

  // 4. Gast zahlt mit Trinkgeld.
  await guest.getByRole('button', { name: 'Mein Besuch' }).click();
  await guest.getByRole('button', { name: 'Bestellstatus aktualisieren' }).click();
  await guest.getByRole('button', { name: 'Zahlen', exact: true }).first().click();
  await guest.getByRole('button', { name: /10 %/ }).click();
  await guest.screenshot({ path: `${root}/tip-guest-pay.png`, fullPage: true });
  await guest.getByRole('button', { name: 'Zahlung anfordern' }).click();
  await guest.getByRole('status').filter({ hasText: 'Trinkgeld angefordert' }).waitFor();
  const tipped = (await call(manager, `/gastro/venues/${venue}/orders`)).find(row => row.id === order.id);
  report.tip_cents = tipped.tip_cents;

  // 5. Die Kasse bestätigt, was sie wirklich kassiert hat.
  const device = await call(manager, `/gastro/venues/${venue}/devices`, 'POST', {
    name: `Kasse ${Math.random().toString(36).slice(2, 6)}`, kind: 'pos', scopes: ['payments:write', 'events:read'],
  });
  const settled = await fetch(`${API.replace('/api', '')}/api/device/v1/payments`, {
    method: 'POST',
    headers: { 'X-FlintPlate-Key': device.token, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      request_key: crypto.randomUUID(), order_id: order.id,
      amount_cents: tipped.total_cents - tipped.voucher_cents + tipped.tip_cents,
      currency: 'EUR', reference: 'browser-journey',
    }),
  });
  report.settled = settled.status;
  if (!settled.ok) throw new Error(`payment ${settled.status}: ${(await settled.text()).slice(0, 200)}`);

  // 6. Verteilung ansehen und festschreiben.
  await office.reload();
  await office.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await office.getByRole('button', { name: 'Team & Dienste' }).click();
  await office.getByRole('button', { name: 'Vorschau' }).click();
  const rows = office.locator('.fp-preview tbody tr');
  await rows.first().waitFor();
  report.preview = await rows.allInnerTexts();
  await office.screenshot({ path: `${root}/tip-preview.png`, fullPage: true });
  await office.getByRole('button', { name: 'Verteilung festschreiben' }).click();
  await office.getByRole('status').filter({ hasText: 'festgeschrieben' }).waitFor();
  const history = await call(manager, `/gastro/venues/${venue}/tips/runs`);
  report.run = { total_cents: history[0].total_cents, shares: history[0].shares.length };
  report.overflow = await office.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  await office.screenshot({ path: `${root}/tip-run.png`, fullPage: true });

  report.errors = errors;
  await desk.close();
  await phone.close();
} finally {
  await browser.close();
}
await fs.writeFile(`${root}/tips.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
