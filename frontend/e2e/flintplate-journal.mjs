import { chromium, expect } from '@playwright/test';
import fs from 'node:fs/promises';

const credentials = JSON.parse(await fs.readFile(new URL('../../backend/.local/demo-access.json', import.meta.url), 'utf8'));
const root = '/tmp/hireos-browser-tests/flintplate';
await fs.mkdir(root, { recursive: true });
const browser = await chromium.launch({ executablePath: '/tmp/palmscout-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell', headless: true, args: ['--disable-gpu', '--disable-dev-shm-usage', '--no-sandbox'] });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, timezoneId: 'Europe/Berlin' });
  page.setDefaultTimeout(30000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', entry => { if (entry.type() === 'error') errors.push(entry.text()); });
  await page.goto('http://localhost:3012/anmelden?next=%2Fgastro');
  await page.getByLabel('E-Mail-Adresse').fill(credentials.manager);
  await page.getByLabel('Passwort', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
  await page.waitForURL('**/gastro');
  await page.getByRole('button', { name: 'Anbindungen & Service', exact: true }).click();
  await page.getByRole('button', { name: 'Journal & Exporte', exact: true }).click();
  const pending = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Journal vollständig exportieren', exact: true }).click();
  const download = await pending;
  expect(download.suggestedFilename()).toBe('flintplate-journal.json');
  await download.saveAs(`${root}/flintplate-journal.json`);
  await expect(page.getByRole('status').filter({ hasText: 'vollständig heruntergeladen' })).toBeVisible();
  const exported = JSON.parse(await fs.readFile(`${root}/flintplate-journal.json`, 'utf8'));
  const rows = exported.items;
  expect(exported.venue_id).toBe(credentials.venue_id);
  expect(rows.every(row => row.sequence <= exported.through_sequence)).toBe(true);
  expect(rows.length).toBeGreaterThan(0);
  expect(rows.every(row => row.venue_id === credentials.venue_id)).toBe(true);
  expect(errors).toEqual([]);
  await page.screenshot({ path: `${root}/journal-desktop.png`, fullPage: true });
  await fs.writeFile(`${root}/journal-ui.json`, JSON.stringify({ downloaded_events: rows.length, errors }, null, 2));
  console.log(`Journal über die sichtbare Oberfläche exportiert: ${rows.length} Ereignisse, keine Browserfehler.`);
} finally { await browser.close(); }
