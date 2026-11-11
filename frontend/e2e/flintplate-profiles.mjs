import { chromium } from '@playwright/test';
import fs from 'node:fs/promises';

const credentials = JSON.parse(await fs.readFile(new URL('../../backend/.local/demo-access.json', import.meta.url), 'utf8'));
const root = '/tmp/hireos-browser-tests/flintplate';
await fs.mkdir(root, { recursive: true });
const name = `Service erfahren ${Math.random().toString(36).slice(2, 6)}`;
const browser = await chromium.launch({ executablePath: '/tmp/palmscout-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell', headless: true, args: ['--disable-gpu', '--disable-dev-shm-usage', '--no-sandbox'] });
const report = { template: name };
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, timezoneId: 'Europe/Berlin' });
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
  await page.getByRole('button', { name: 'Team & Dienste' }).click();

  // 1. Vorlage anlegen
  await page.getByRole('button', { name: 'Vorlage', exact: false }).first().click();
  await page.getByLabel('Name').fill(name);
  await page.getByLabel('Wofür steht diese Vorlage?').fill('Getränke, Gastkontakt, Einarbeitung.');
  await page.getByRole('checkbox', { name: 'Service' }).check();
  await page.getByRole('checkbox', { name: 'Bar' }).check();
  await page.getByLabel('Erfahrungsstufe').selectOption('4');
  await page.getByRole('button', { name: 'Vorlage anlegen' }).click();
  const card = page.locator('.fp-template').filter({ hasText: name });
  await card.waitFor();
  report.created = await card.innerText();

  // 2. Einer Person zuweisen
  const row = page.locator('.fp-panel table tbody tr').first();
  report.person = await row.locator('strong').innerText();
  await row.locator('select').selectOption({ label: name });
  await page.getByRole('status').filter({ hasText: 'Vorlage zugewiesen' }).waitFor();
  report.after_assign = (await row.innerText()).split('\n').filter(Boolean);

  // 3. Erfahrung eigenständig machen
  await row.getByTitle('Wert von der Vorlage lösen').last().click();
  await page.getByRole('status').filter({ hasText: 'eigenständig gepflegt' }).waitFor();
  report.after_override = (await row.innerText()).split('\n').filter(Boolean);
  await page.screenshot({ path: `${root}/profiles-overview.png`, fullPage: true });

  // 4. Vorlage ändern, Vorschau bestätigen
  await card.getByRole('button', { name: 'Bearbeiten' }).click();
  await page.getByLabel('Erfahrungsstufe').selectOption('2');
  await page.getByRole('checkbox', { name: 'Küche' }).check();
  await page.getByRole('button', { name: 'Änderung prüfen' }).click();
  await page.getByRole('heading', { name: 'Das ändert sich' }).waitFor();
  report.impact = await page.locator('.fp-change-list li').allInnerTexts();
  report.shielded = await page.locator('.fp-hint').last().innerText();
  await page.screenshot({ path: `${root}/profiles-impact.png` });
  await page.getByRole('button', { name: 'Übernehmen', exact: true }).click();
  await page.getByRole('status').filter({ hasText: 'Vorlage übernommen' }).waitFor();

  // 5. Eigener Wert hat überlebt
  await page.reload();
  await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await page.getByRole('button', { name: 'Team & Dienste' }).click();
  const again = page.locator('.fp-panel table tbody tr').first();
  await again.waitFor();
  report.after_template_change = (await again.innerText()).split('\n').filter(Boolean);
  report.overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  await page.screenshot({ path: `${root}/profiles-after.png`, fullPage: true });

  report.errors = errors;
  await context.close();
} finally {
  await browser.close();
}
await fs.writeFile(`${root}/profiles.json`, JSON.stringify(report, null, 2));
console.log(JSON.stringify(report, null, 2));
