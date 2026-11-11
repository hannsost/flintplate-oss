import { chromium } from '@playwright/test';
import fs from 'node:fs/promises';

const credentials = JSON.parse(await fs.readFile(new URL('../../backend/.local/demo-access.json', import.meta.url), 'utf8'));
const root = '/tmp/hireos-browser-tests/flintplate';
await fs.mkdir(root, { recursive: true });
const browser = await chromium.launch({ executablePath: '/tmp/palmscout-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell', headless: true, args: ['--disable-gpu', '--disable-dev-shm-usage', '--no-sandbox'] });
const results = [];
try {
  for (const [role, destination, width, height] of [
    ['manager', '/gastro', 1440, 1000],
    ['worker', '/team', 390, 844],
    ['guest', `/kunden/${credentials.venue_id}`, 390, 844],
  ]) {
    const context = await browser.newContext({ viewport: { width, height }, timezoneId: 'Europe/Berlin' });
    const page = await context.newPage(); page.setDefaultTimeout(120000);
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('console', entry => { if (entry.type() === 'error') errors.push(entry.text()); });
    await page.goto(`http://localhost:3012/anmelden?next=${encodeURIComponent(destination)}`, { timeout: 180000 });
    await page.getByLabel('E-Mail-Adresse').fill(credentials[role]);
    await page.getByLabel('Passwort', { exact: true }).fill(credentials.password);
    await page.getByRole('button', { name: 'Anmelden', exact: true }).click();
    await page.waitForURL(`**${destination}`, { timeout: 180000 });
    await page.getByRole('heading', { level: 1 }).waitFor();
    await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
    if (await page.getByRole('button', {name: 'Erneut laden', exact:true}).isVisible()) { await page.getByRole('button', {name:'Erneut laden',exact:true}).click(); await page.getByRole('button', {name:'Erneut laden',exact:true}).waitFor({state:'hidden'}); }
    await page.screenshot({ path: `${root}/${role}-${width}.png`, fullPage: true });
    results.push({ role, url: page.url(), width, heading: await page.getByRole('heading', { level: 1 }).innerText(),
      overflow: await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),
      alerts: await page.getByRole('alert').allTextContents(), errors,
      buttons: await page.getByRole('button').allTextContents() });
    await fs.writeFile(`${root}/probe.json`, JSON.stringify(results, null, 2));
    console.log(`${role}: ${page.url()} rendered`);
    await context.close();
  }
} finally { await browser.close(); }
