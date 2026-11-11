import { chromium } from '@playwright/test';
import fs from 'node:fs/promises';

const credentials = JSON.parse(await fs.readFile(new URL('../../backend/.local/demo-access.json', import.meta.url), 'utf8'));
const root = '/tmp/hireos-browser-tests/flintplate';
await fs.mkdir(root, { recursive: true });
const person = `Familie Sommer ${Math.random().toString(36).slice(2, 6)}`;
const report = { person };
const browser = await chromium.launch({ executablePath: '/tmp/palmscout-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell', headless: true, args: ['--disable-gpu', '--disable-dev-shm-usage', '--no-sandbox'] });
const errors = [];
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1100 }, timezoneId: 'Europe/Berlin' });
  const page = await context.newPage();
  page.setDefaultTimeout(120000);
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', item => { if (item.type() === 'error') errors.push(item.text()); });
  page.on('dialog', dialog => { report.dialog = dialog.message(); void dialog.accept(); });

  await page.goto('http://localhost:3012/anmelden?next=%2Fgastro', { timeout: 180000 });
  await page.getByLabel('E-Mail-Adresse').fill(credentials.manager);
  await page.getByLabel('Passwort', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await page.waitForURL('**/gastro', { timeout: 180000 });
  await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await page.getByRole('button', { name: 'Gäste & Vorteile' }).click();

  // Aufnehmen
  await page.getByRole('button', { name: 'Gast aufnehmen' }).click();
  await page.getByLabel('Name oder Ansprache').fill(person);
  await page.getByLabel('Merkhilfe für das Team').fill('Stammtisch Freitag, sitzt hinten links');
  await page.getByLabel('Geburtstag als TT.MM (freiwillig)').fill('04.05');
  await page.getByRole('button', { name: 'Aufnehmen', exact: true }).click();
  const card = page.locator('.fp-guest-card').filter({ hasText: person });
  await card.waitFor();
  report.card = await card.innerText();

  // Öffnen und eine Gesundheitsnotiz ohne Einwilligung versuchen
  await card.click();
  await page.getByRole('heading', { name: person }).waitFor();
  await page.getByLabel('Was soll das Team wissen?').fill('Erdnussallergie, bitte immer nachfragen.');
  await page.getByLabel('Art').selectOption('gesundheit');
  await page.getByRole('button', { name: 'Notiz hinzufügen' }).click();
  const alarm = page.locator('.fp-notice.error');
  await alarm.waitFor();
  report.refusal = await alarm.innerText();

  // Einwilligung festhalten, dann geht es
  await page.getByRole('button', { name: 'Einwilligung festhalten' }).click();
  await page.getByRole('status').filter({ hasText: 'Einwilligung festgehalten' }).waitFor();
  await page.getByLabel('Was soll das Team wissen?').fill('Erdnussallergie, bitte immer nachfragen.');
  await page.getByLabel('Art').selectOption('gesundheit');
  await page.getByRole('button', { name: 'Notiz hinzufügen' }).click();
  await page.getByRole('status').filter({ hasText: 'Notiz gespeichert' }).waitFor();

  // Eine persönliche Notiz
  await page.getByLabel('Was soll das Team wissen?').fill('Hat vom Umzug nach Kiel erzählt.');
  await page.getByLabel('Art').selectOption('gespraech');
  await page.getByLabel('Sichtbar für').selectOption('private');
  await page.getByRole('button', { name: 'Notiz hinzufügen' }).click();
  await page.getByRole('status').filter({ hasText: 'Notiz gespeichert' }).waitFor();

  const notes = page.locator('.fp-note');
  await notes.first().waitFor();
  report.notes = await notes.allInnerTexts();
  report.hints = await page.locator('.fp-hint').allInnerTexts();
  await page.screenshot({ path: `${root}/guestbook-detail.png`, fullPage: true });

  // Widerruf löscht genau die Gesundheitsnotiz
  await page.getByRole('button', { name: 'Einwilligung widerrufen' }).click();
  await page.getByRole('status').filter({ hasText: 'widerrufen' }).waitFor();
  report.after_revoke = await page.locator('.fp-note').allInnerTexts();
  report.overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  await page.screenshot({ path: `${root}/guestbook-after-revoke.png`, fullPage: true });

  await context.close();
} catch (error) {
  report.failed = String(error).split('\n')[0];
} finally {
  await browser.close();
  report.errors = errors;
  await fs.writeFile(`${root}/guestbook.json`, JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
}
