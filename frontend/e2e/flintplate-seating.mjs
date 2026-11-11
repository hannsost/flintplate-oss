import { chromium } from '@playwright/test';
import fs from 'node:fs/promises';

const credentials = JSON.parse(await fs.readFile(new URL('../../backend/.local/demo-access.json', import.meta.url), 'utf8'));
const root = '/tmp/hireos-browser-tests/flintplate';
await fs.mkdir(root, { recursive: true });
const stamp = new Date(Date.now() + 6 * 86400000);
stamp.setHours(18, 0, 0, 0);
const local = value => `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}T${String(value.getHours()).padStart(2, '0')}:${String(value.getMinutes()).padStart(2, '0')}`;
const guestName = `KI-Vorschlag ${Math.random().toString(36).slice(2, 7)}`;
const browser = await chromium.launch({ executablePath: '/tmp/palmscout-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell', headless: true, args: ['--disable-gpu', '--disable-dev-shm-usage', '--no-sandbox'] });
const report = { guest_name: guestName, start: local(stamp) };
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, timezoneId: 'Europe/Berlin' });
  const page = await context.newPage();
  page.setDefaultTimeout(120000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', entry => { if (entry.type() === 'error') errors.push(entry.text()); });

  await page.goto('http://localhost:3012/anmelden?next=%2Fgastro', { timeout: 180000 });
  await page.getByLabel('E-Mail-Adresse').fill(credentials.manager);
  await page.getByLabel('Passwort', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await page.waitForURL('**/gastro', { timeout: 180000 });
  await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });

  await page.getByRole('button', { name: 'Reservierungen' }).click();
  await page.getByRole('button', { name: 'Platz vorschlagen' }).click();
  await page.getByLabel('Beginn (Gerätezeit)').fill(local(stamp));
  await page.getByLabel('Personen').fill('4');
  await page.getByLabel('Zusätzliche Punkte für die Entscheidung').fill('Heute Abend viel Laufkundschaft, große Runden zusammenhalten.');
  await page.screenshot({ path: `${root}/seating-form.png` });
  await page.getByRole('button', { name: 'Drei Vorschläge zeigen' }).click();

  const options = page.locator('.fp-option');
  await options.first().waitFor();
  report.option_count = await options.count();
  report.options = [];
  for (let index = 0; index < report.option_count; index += 1) {
    const card = options.nth(index);
    report.options.push({
      title: await card.locator('strong').innerText(),
      reasons: await card.locator('ul:not(.fp-option-tradeoffs) li').allTextContents(),
      tradeoffs: await card.locator('.fp-option-tradeoffs li').allTextContents(),
    });
  }
  report.prompt_note = await page.locator('.fp-description').last().innerText();
  await page.screenshot({ path: `${root}/seating-options.png`, fullPage: true });

  const second = options.nth(Math.min(1, report.option_count - 1));
  await second.locator('input[type=radio]').check();
  report.chosen = await second.locator('strong').innerText();
  await page.getByLabel('Name des Gastes / der Gruppe').fill(guestName);
  await page.getByRole('button', { name: 'Gewählten Vorschlag reservieren' }).click();

  await page.getByRole('status').filter({ hasText: 'Vorschlag angenommen' }).waitFor();
  await page.reload();
  await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await page.getByRole('button', { name: 'Reservierungen' }).click();
  await page.getByRole('cell', { name: guestName }).waitFor();
  report.persisted_after_reload = true;
  report.overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  await page.screenshot({ path: `${root}/seating-booked.png`, fullPage: true });

  report.errors = errors;
  await context.close();
} finally {
  await browser.close();
}
await fs.writeFile(`${root}/seating.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
