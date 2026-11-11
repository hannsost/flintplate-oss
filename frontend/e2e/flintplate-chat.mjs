import { chromium } from '@playwright/test';
import fs from 'node:fs/promises';

const credentials = JSON.parse(await fs.readFile(new URL('../../backend/.local/demo-access.json', import.meta.url), 'utf8'));
const root = '/tmp/hireos-browser-tests/flintplate';
await fs.mkdir(root, { recursive: true });
const note = `Nachschub bestellt ${Math.random().toString(36).slice(2, 6)}`;
const report = { note };
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
  // Die Leitung schreibt aus der Betriebsoberfläche.
  const desk = await browser.newContext({ viewport: { width: 1440, height: 1100 }, timezoneId: 'Europe/Berlin' });
  const office = await desk.newPage();
  office.setDefaultTimeout(120000);
  watch(office);
  await signIn(office, credentials.manager, '/gastro');
  await office.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await office.getByRole('button', { name: 'Team & Dienste' }).click();
  await office.getByRole('heading', { name: 'Team-Chat' }).waitFor();
  await office.getByLabel('Nachricht').fill(note);
  await office.getByRole('button', { name: 'Senden' }).click();
  const mine = office.locator('.fp-message').filter({ hasText: note });
  await mine.waitFor();
  report.sent = await mine.innerText();
  await office.screenshot({ path: `${root}/chat-office.png`, fullPage: true });

  // Das Team sieht sie im Handy, ohne etwas zu drücken.
  const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, timezoneId: 'Europe/Berlin' });
  const worker = await phone.newPage();
  worker.setDefaultTimeout(120000);
  watch(worker);
  await signIn(worker, credentials.worker, '/team');
  await worker.getByRole('button', { name: 'Chat' }).click();
  const arrived = worker.locator('.fp-message').filter({ hasText: note });
  await arrived.waitFor();
  report.received = await arrived.innerText();
  report.foreign = !(await arrived.innerText()).startsWith('Du');

  // Antwort zurück, und die Leitung bekommt sie von selbst.
  const reply = `Danke, notiert ${Math.random().toString(36).slice(2, 5)}`;
  await worker.getByLabel('Nachricht').fill(reply);
  await worker.getByRole('button', { name: 'Senden' }).click();
  await worker.locator('.fp-message').filter({ hasText: reply }).waitFor();
  await worker.screenshot({ path: `${root}/chat-phone.png`, fullPage: true });

  const started = Date.now();
  await office.locator('.fp-message').filter({ hasText: reply }).waitFor({ timeout: 60000 });
  report.live_seconds = Math.round((Date.now() - started) / 1000);
  report.overflow = await worker.evaluate(() => document.documentElement.scrollWidth > innerWidth);

  await desk.close();
  await phone.close();
} catch (error) {
  report.failed = String(error).split('\n')[0];
} finally {
  await browser.close();
  report.errors = errors;
  await fs.writeFile(`${root}/chat.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
}
