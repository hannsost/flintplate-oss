import { chromium, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import fs from 'node:fs/promises';
import { fulfillFromIsolatedApi, requestIsolatedApi } from './flintplate-browser-api.mjs';

// Requires the completed main ERP journey in the same isolated acceptance schema.
// Its unblocked PURCHASE-BROWSER lot supplies this second production journey.
const socket = process.env.FLINTPLATE_BROWSER_SOCKET;
if (!socket) throw new Error('Isolated acceptance socket required; demo writes are forbidden.');
const credentials = JSON.parse(await fs.readFile(process.env.FLINTPLATE_BROWSER_CREDENTIALS ?? new URL('../../backend/.local/browser-acceptance-access.json', import.meta.url), 'utf8'));
const resume = process.env.FLINTPLATE_PRODUCTION_RESUME === '1';
const output = '/tmp/hireos-browser-tests/flintplate-production-acceptance' + (resume ? '-continuation' : '');
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH ?? '/tmp/palmscout-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell', headless: true, args: ['--disable-gpu', '--disable-dev-shm-usage', '--no-sandbox'] });
const context = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 1440, height: 1050 }, timezoneId: 'Europe/Berlin', acceptDownloads: true });
const page = await context.newPage(); page.setDefaultTimeout(45000);
const report = { isolated: true, checks: [], screenshots: [], errors: [], writes: [] };
page.on('pageerror', error => report.errors.push(error.message));
page.on('response', response => { if (response.url().includes('/api/') && response.request().method() === 'GET' && response.status() >= 400) report.errors.push(`${response.status()} GET ${new URL(response.url()).pathname}`); });
async function routeApi(target, readOnly = false) {
  await target.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== 'http://localhost:3012' || !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) { report.errors.push(`Blocked unproxied request: ${request.method()} ${url.pathname}`); await route.abort('blockedbyclient'); }
    else await route.continue();
  });
  await target.route('**/api/**', async route => {
    const request = route.request(), path = new URL(request.url()).pathname;
    if (readOnly && !['GET', 'HEAD', 'OPTIONS'].includes(request.method()) && !path.includes('/auth/')) { report.errors.push(`Blocked kitchen read-only write: ${request.method()} ${path}`); await route.abort('blockedbyclient'); }
    else await fulfillFromIsolatedApi(route, socket);
  });
}
await routeApi(context);
const modal = () => page.getByRole('dialog');
const card = name => page.locator('article.fp-panel').filter({ has: page.getByRole('heading', { name, exact: true }) });
async function nav(name) { await page.getByRole('navigation', { name: 'Betriebsnavigation' }).getByRole('button', { name, exact: false }).click(); await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' }); }
async function write(click, suffix, expected = 201) {
  const [response] = await Promise.all([page.waitForResponse(response => response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith(suffix)), click()]); const data = await response.json();
  report.writes.push({ path: new URL(response.url()).pathname, status: response.status() }); console.log(JSON.stringify({ checkpoint: suffix, status: response.status() }));
  expect(response.status(), JSON.stringify(data)).toBe(expected); return data;
}
async function save(suffix) { const data = await write(() => modal().getByRole('button', { name: 'Verbindlich speichern', exact: true }).click(), suffix); await expect(modal()).toHaveCount(0); return data; }
async function option(label, startsWith) {
  const select = modal().getByLabel(label, { exact: true });
  await select.selectOption(await select.locator('option').filter({ hasText: new RegExp(`^${startsWith}`) }).getAttribute('value'));
}
async function shot(name, target = page) {
  await target.evaluate(async () => { await Promise.all(document.getAnimations().filter(animation => animation.effect?.getComputedTiming().iterations !== Infinity).map(animation => animation.finished.catch(() => undefined))); });
  const axe = await new AxeBuilder({ page: target }).include('.fp').withTags(['wcag2a', 'wcag2aa', 'wcag21aa']).analyze();
  const overflow = await target.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
  const path = `${output}/${name}.png`; await target.screenshot({ path, fullPage: target.viewportSize().width > 700 });
  report.screenshots.push({ path, viewport: target.viewportSize(), overflow, violations: axe.violations.map(item => ({ id: item.id, targets: item.nodes.map(node => node.target) })) });
  expect(overflow).toBe(false); expect(axe.violations).toEqual([]);
}
async function production(recipe, quantity, batches, code) {
  await page.getByRole('button', { name: 'Mise en place', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Produktion buchen', exact: true })).toBeEnabled(); await page.getByRole('button', { name: 'Produktion buchen', exact: true }).click();
  await option('Rezeptversion', recipe); await modal().getByLabel('Rezeptansätze').fill(batches); await modal().getByLabel('Tatsächliche Ausbeute').fill(quantity);
  await modal().getByLabel('Neue Chargennummer').fill(code); await modal().getByLabel('MHD laut Hygienekonzept').fill(new Date(Date.now() + 7 * 86400000).toISOString().slice(0, 10));
  await save('/prep');
  await expect(page.getByRole('button', { name: 'Produktion buchen', exact: true })).toBeEnabled();
}
async function recipeVersion(name) {
  await page.getByRole('button', { name: 'Rezepturen', exact: true }).click(); await expect(page.getByRole('button', { name: 'Rezeptur anlegen', exact: true })).toBeEnabled(); await page.getByRole('button', { name: 'Rezeptur anlegen', exact: true }).click();
  await modal().getByLabel('Rezeptname').fill(name); await option('Ausgabeartikel im Lager', 'Fertige Unterrezeptportion');
  await modal().getByLabel('Geplante Ausbeute').fill('1'); await modal().getByLabel('Gericht auf der Karte (optional)').selectOption({ label: 'Testgericht' });
  await option('Lagerartikel', 'Prepportion'); await option('Vorbereitete Zutat aus Unterrezept', 'Basis-Prep ·');
  await expect(modal().getByLabel('Netto-Einstandskosten je Basiseinheit in Cent')).toHaveValue('40'); await expect(modal().getByLabel('Netto-Einstandskosten je Basiseinheit in Cent')).toBeDisabled();
  await expect(modal().getByLabel('Allergene, mit Komma getrennt')).toBeDisabled(); await expect(modal().getByLabel('Allergene, mit Komma getrennt')).toHaveValue(/gluten/);
  await modal().getByLabel('Mengen und Allergene anhand der Zutaten und Lieferantenangaben geprüft.').check();
  const recipe = await save('/recipes'); expect(recipe.cost_cents).toBe(40); expect(recipe.allergens).toEqual(expect.arrayContaining(['gluten', 'milch'])); expect(recipe.components[0].subrecipe_id).toBeTruthy();
  return recipe;
}
try {
  await page.goto('http://localhost:3012/anmelden?next=%2Fgastro'); await page.getByLabel('E-Mail-Adresse').fill(credentials.manager); await page.getByLabel('Passwort', { exact: true }).fill(credentials.password);
  await page.getByRole('button', { name: 'Anmelden', exact: true }).click(); await page.waitForURL('**/gastro'); await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  let activeRecipe;
  if (!resume) {
  await nav('Lager & Waren'); await page.getByRole('button', { name: 'Artikel & Orte', exact: true }).click(); await page.getByRole('button', { name: 'Artikel', exact: true }).click();
  await modal().getByLabel('Lagernummer').fill('BROWSER-FINAL'); await modal().getByLabel('Artikelname').fill('Fertige Unterrezeptportion'); await modal().getByLabel('Basiseinheit').selectOption('piece');
  await write(() => modal().getByRole('button', { name: 'Anlegen', exact: true }).click(), '/items'); await expect(modal()).toHaveCount(0);
  await nav('Produktion & Hygiene');
  await production('Basis-Prep ·', '4', '1', 'FRESH-SUB-BROWSER');
  await shot('produktion-ausbeute-stabile-tabs');
  activeRecipe = await recipeVersion('Browser Gericht mit Unterrezept');
  await production('Browser Gericht mit Unterrezept ·', '2', '2', 'FINAL-SUB-BROWSER');
  await nav('Lager & Waren'); await expect(page.getByRole('row').filter({ hasText: 'FRESH-SUB-BROWSER' })).toContainText('2 Stück'); await expect(page.getByRole('row').filter({ hasText: 'FINAL-SUB-BROWSER' })).toContainText('2 Stück');
  report.checks.push('Frische Basis-Prep entsteht aus dem Einkaufseingang. Gebundenes Unterrezept übernimmt 40 Cent und Allergene; zwei Endportionen verbrauchen genau zwei passende Prepportionen.');

  await page.getByRole('button', { name: 'Daten aktualisieren', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Daten aktualisieren', exact: true })).toBeEnabled();
  await nav('Karte & Preise'); const menuRow = page.getByRole('row').filter({ hasText: 'Testgericht' });
  await write(() => menuRow.getByRole('button', { name: 'Veröffentlichen', exact: true }).click(), '/publish', 200);
  await expect(page.getByRole('button', { name: 'Daten aktualisieren', exact: true })).toBeEnabled();
  await nav('Bestellungen'); await page.getByRole('button', { name: 'To go', exact: true }).click(); await page.getByRole('button', { name: 'Testgericht hinzufügen', exact: true }).click();
  } else {
    report.continuationOf = '/tmp/hireos-browser-tests/flintplate-production-acceptance/report.json';
    await nav('Bestellungen'); await page.getByRole('button', { name: 'To go', exact: true }).click(); await page.getByRole('button', { name: 'Testgericht hinzufügen', exact: true }).click();
    await nav('Produktion & Hygiene'); activeRecipe = await recipeVersion('Browser Gericht Folgeversion');
    await page.getByRole('button', { name: 'Daten aktualisieren', exact: true }).click(); await expect(page.getByRole('button', { name: 'Daten aktualisieren', exact: true })).toBeEnabled();
    await nav('Karte & Preise'); await write(() => page.getByRole('row').filter({ hasText: 'Testgericht' }).getByRole('button', { name: 'Veröffentlichen', exact: true }).click(), '/publish', 200);
    await expect(page.getByRole('button', { name: 'Daten aktualisieren', exact: true })).toBeEnabled();
    await nav('Bestellungen');
    await expect(page.getByRole('button', { name: 'Aktuelle Karte übernehmen', exact: true })).toBeVisible();
    await expect(page.getByRole('button', { name: 'An Küche & Bar senden', exact: true })).toBeDisabled();
    await page.locator('.fp-cart').scrollIntoViewIfNeeded(); await shot('kartenwechsel-erfordert-bewusste-uebernahme');
    await page.getByRole('button', { name: 'Aktuelle Karte übernehmen', exact: true }).click();
    await expect(page.getByRole('button', { name: 'An Küche & Bar senden', exact: true })).toBeEnabled();
    report.checks.push('Vorhandener Entwurf bleibt nach echter neuer Rezept-/Kartenveröffentlichung erhalten, ist bis zur sichtbaren Übernahme gesperrt und übernimmt danach die aktuelle Revision.');
  }
  const order = await write(() => page.getByRole('button', { name: 'An Küche & Bar senden', exact: true }).click(), '/orders');
  expect(order.lines[0].menu_version).toBe(activeRecipe.menu_version); expect(order.lines[0].recipe_id).toBe(activeRecipe.id);
  await nav('Küche & Bar'); const ticket = page.locator('.fp-kitchen-ticket').filter({ hasText: order.number });
  await write(() => ticket.getByRole('button', { name: 'Testgericht: Starten', exact: true }).click(), '/status', 200);
  await expect(page.getByRole('button', { name: 'Daten aktualisieren', exact: true })).toBeEnabled();
  const traced = page.waitForResponse(response => new URL(response.url()).pathname.endsWith(`/${order.id}/provenance`) && response.ok());
  await ticket.getByRole('button', { name: `Zutatenherkunft für ${order.number}`, exact: true }).click();
  const trace = await (await traced).json(); expect(trace.receipts).toHaveLength(1); expect(trace.lots.map(lot => lot.code)).toEqual(expect.arrayContaining(['PURCHASE-BROWSER', 'FRESH-SUB-BROWSER']));
  await expect(modal()).toContainText('PURCHASE-BROWSER'); await expect(modal()).toContainText('FRESH-SUB-BROWSER'); await expect(modal()).toContainText('Zugehörige Wareneingänge'); await shot('gericht-unterrezept-wareneingang-herkunft'); await page.keyboard.press('Escape');
  for (const label of ['Fertig', 'Servieren']) {
    await write(() => ticket.getByRole('button', { name: `Testgericht: ${label}`, exact: true }).click(), '/status', 200);
    await expect(page.getByRole('button', { name: 'Daten aktualisieren', exact: true })).toBeEnabled();
    if (label === 'Fertig') {
      if (!credentials.kitchen) throw new Error('Current isolated fixture must include a kitchen-role user.');
      const kitchenContext = await browser.newContext({ serviceWorkers: 'block', viewport: { width: 1440, height: 1050 }, timezoneId: 'Europe/Berlin' });
      await routeApi(kitchenContext, true); const kitchenPage = await kitchenContext.newPage(); kitchenPage.setDefaultTimeout(45000);
      kitchenPage.on('pageerror', error => report.errors.push(error.message));
      await kitchenPage.goto('http://localhost:3012/anmelden?next=%2Fgastro'); await kitchenPage.getByLabel('E-Mail-Adresse').fill(credentials.kitchen); await kitchenPage.getByLabel('Passwort', { exact: true }).fill(credentials.password);
      await kitchenPage.getByRole('button', { name: 'Anmelden', exact: true }).click(); await kitchenPage.waitForURL('**/gastro'); await kitchenPage.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
      await kitchenPage.getByRole('navigation', { name: 'Betriebsnavigation' }).getByRole('button', { name: 'Küche & Bar', exact: true }).click();
      const kitchenTicket = kitchenPage.locator('.fp-kitchen-ticket').filter({ hasText: order.number }); await expect(kitchenTicket).toContainText('Fertig');
      await expect(kitchenTicket.getByRole('button', { name: 'Testgericht: Servieren', exact: true })).toHaveCount(0);
      await kitchenTicket.getByRole('button', { name: `Zutatenherkunft für ${order.number}`, exact: true }).click(); await expect(kitchenPage.getByRole('dialog')).toContainText('PURCHASE-BROWSER');
      await shot('kuechenrolle-herkunft-ohne-serviceaktion', kitchenPage); await kitchenContext.close();
      report.checks.push('Echte Küchenmitgliedschaft kann Zutatenherkunft lesen, besitzt aber keine Servieren-Aktion am fertigen Gericht. Küchenkontext erlaubt im Test ausschließlich lesende Geschäftsaufrufe.');
    }
  }
  await nav('Bestellungen'); const served = page.locator('.fp-kitchen-ticket').filter({ hasText: order.number });
  await write(() => served.getByRole('button', { name: 'An Kasse übergeben', exact: true }).click(), '/checkout', 200); await expect(served).toContainText('Wartet auf Kassenbestätigung');
  await served.getByRole('button', { name: `Zutatenherkunft für ${order.number}`, exact: true }).click(); await expect(modal()).toContainText('FRESH-SUB-BROWSER'); await page.keyboard.press('Escape');
  report.checks.push('Veröffentlichtes Gericht verbraucht beim Küchenstart die gebundene Prepversion; Zutatenherkunft führt über Prep bis PURCHASE-BROWSER und den Wareneingang und bleibt nach Checkout lesbar.');

  await nav('Produktion & Hygiene'); await page.getByRole('button', { name: 'Kontrollpläne', exact: true }).click(); await page.getByRole('button', { name: 'Kontrollplan', exact: true }).click();
  await modal().getByLabel('Kontrollaufgabe').fill('Browser Kühlplan'); await modal().getByLabel('Ort oder Gerät').fill('Kühlhaus'); await modal().getByLabel('Prüfanweisung').fill('Temperatur ablesen und bei Abweichung sofort handeln.');
  await modal().getByLabel('Untergrenze', { exact: true }).fill('0'); await modal().getByLabel('Obergrenze', { exact: true }).fill('7'); await modal().getByLabel('Einheit', { exact: true }).fill('°C'); await modal().getByLabel('Intervall in Minuten').fill('60'); await modal().getByLabel('Verantwortlich', { exact: true }).selectOption({ label: 'Test Leitung' });
  const plan = await write(() => modal().getByRole('button', { name: 'Plan speichern', exact: true }).click(), '/hygiene/plans'); await expect(modal()).toHaveCount(0); await expect(card('Browser Kühlplan')).toContainText('Fällig');
  await card('Browser Kühlplan').getByRole('button', { name: 'Kontrolle erfassen', exact: true }).click(); await modal().getByLabel('Messwert (°C)').fill('10'); await modal().getByLabel('Sofortmaßnahme bei Abweichung').fill('Ware umgelagert und Kühlung kontrolliert.');
  const checks = [];
  await page.route(`**/api/gastro/venues/*/hygiene/plans/${plan.plan_id}/checks`, async route => {
    checks.push(route.request().postDataJSON()); const response = await requestIsolatedApi(route.request(), socket);
    if (checks.length === 1) { expect(response.status).toBe(201); await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ detail: 'Prüfung: Nachweis gespeichert, Antwort gezielt verloren.' }) }); }
    else await route.fulfill(response);
  });
  await write(() => modal().getByRole('button', { name: 'Kontrolle speichern', exact: true }).click(), '/checks', 503); await expect(modal().getByLabel('Messwert (°C)')).toBeDisabled();
  await page.reload(); await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' }); await nav('Produktion & Hygiene'); await page.getByRole('button', { name: 'Kontrollpläne', exact: true }).click();
  await write(() => page.getByRole('button', { name: 'Vorgang erneut prüfen', exact: true }).click(), '/checks'); expect(checks).toHaveLength(2); expect(checks[1]).toEqual(checks[0]);
  await expect(card('Browser Kühlplan')).toContainText('Offene Abweichung: 10 °C'); await expect(card('Browser Kühlplan').getByRole('button', { name: 'Nachkontrolle erfassen', exact: true })).toBeEnabled(); await card('Browser Kühlplan').getByRole('button', { name: 'Nachkontrolle erfassen', exact: true }).click();
  await modal().getByLabel('Messwert (°C)').fill('4'); const followup = await write(() => modal().getByRole('button', { name: 'Kontrolle speichern', exact: true }).click(), '/checks'); expect(followup.result).toBe('ok'); await expect(modal()).toHaveCount(0);
  await expect(card('Browser Kühlplan')).not.toContainText('Offene Abweichung'); await expect(card('Browser Kühlplan')).toContainText('Erledigt');
  await card('Browser Kühlplan').getByRole('button', { name: 'Plan anpassen', exact: true }).click(); await modal().getByLabel('Obergrenze', { exact: true }).fill('6');
  const updated = await write(() => modal().getByRole('button', { name: 'Plan speichern', exact: true }).click(), '/hygiene/plans'); expect(updated.version).toBe(2); await expect(modal()).toHaveCount(0); await expect(card('Browser Kühlplan')).toContainText('Version 2'); await expect(card('Browser Kühlplan')).toContainText('Fällig');
  const download = page.waitForEvent('download'); await page.getByRole('button', { name: 'CSV-Nachweise · 30 Tage', exact: true }).click(); const file = await download; const csvPath = `${output}/kontrollnachweise.csv`; await file.saveAs(csvPath);
  const csv = await fs.readFile(csvPath, 'utf8'); expect(csv).toContain('Nachkontrolle zu'); expect(csv).toContain('Browser Kühlplan'); expect(csv).toContain('Ware umgelagert'); expect(csv).toContain('Test Leitung'); report.csv = csvPath;
  await shot('kontrollplan-versionierte-nachweise'); await page.setViewportSize({ width: 390, height: 844 }); await shot('kontrollplan-mobil');
  report.checks.push('Hygieneplan mit Verantwortung: 10 °C Abweichung, echte Buchung mit verlorener Antwort und identischem Reload-Retry, 4 °C Nachkontrolle, neue Planversion wieder fällig; CSV enthält unveränderte alte Nachweise und Personenbezug.');
  expect(report.errors).toEqual([]);
} catch (error) { report.failure = error.stack; const path = `${output}/failure.png`; await page.screenshot({ path, fullPage: true }).catch(() => {}); report.screenshots.push({ path }); }
finally { await fs.writeFile(`${output}/report.json`, JSON.stringify(report, null, 2)); await browser.close(); }
console.log(JSON.stringify(report, null, 2)); if (report.failure) process.exitCode = 1;
