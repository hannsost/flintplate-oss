import { acceptance, expect } from './flintplate-acceptance-runner.mjs';

// Real visible service controls; every API call is proxied to a disposable
// migrated schema. No synthetic visit is inserted through a hidden setup API.
const t = await acceptance('flintplate-guest-rounds-acceptance');
const { page, nav, modal, write, report } = t;
const composer = () => page.locator('[data-round="true"]');
const chips = () => page.getByLabel('Gäste dieser Runde', { exact: true });
const chip = name => chips().getByRole('button', { name, exact: true });
const add = name => composer().getByRole('button', { name: `${name} hinzufügen`, exact: true }).click();
const undo = () => composer().getByRole('button', { name: 'Rückgängig', exact: true });
const ticket = number => page.locator('.fp-kitchen-ticket').filter({ hasText: number });

async function visitMode() {
  await nav('Bestellungen');
  await page.getByRole('button', { name: 'Gäste & Runden', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Neuer Besuch', exact: true })).toBeEnabled();
}

async function createVisit(label, guests, tableName = 'T01') {
  await page.getByRole('button', { name: 'Neuer Besuch', exact: true }).click();
  const table = modal().getByLabel('Tisch (optional)', { exact: true });
  const id = await table.locator('option').filter({ hasText: new RegExp(`^${tableName}$`) }).getAttribute('value');
  await table.selectOption(id);
  await modal().getByLabel('Gäste', { exact: true }).fill(String(guests));
  await modal().getByLabel('Gruppenname (optional)', { exact: true }).fill(label);
  const result = await write(() => modal().getByRole('button', { name: 'Besuch eröffnen', exact: true }).click(), '/service-visits');
  await expect(modal()).toHaveCount(0);
  await expect(chip('Gast 1')).toBeEnabled();
  return result;
}

let failure;
try {
  await t.login();
  await visitMode();
  for (const workflow of ['guest', 'counter', 'mixed', 'table']) {
    await page.getByRole('button', { name: 'Arbeitsweise einstellen', exact: true }).click();
    await modal().getByLabel('Standardansicht', { exact: true }).selectOption(workflow);
    await modal().getByLabel('Gäste anzeigen als', { exact: true }).selectOption('number');
    const settings = await write(() => modal().getByRole('button', { name: 'Arbeitsweise speichern', exact: true }).click(), '/service-settings', 201, 'PUT');
    expect(settings.workflow).toBe(workflow);
    await expect(modal()).toHaveCount(0);
    await expect(page.locator('.fp-visits')).toHaveAttribute('data-service-workflow', workflow);
  }
  report.checks.push('Alle vier Betriebsweisen über die Leitungseinstellung gespeichert; Gastnummer bleibt ohne Namenspflicht nutzbar.');

  const first = await createVisit('Freunde am Fenster', 2);
  expect(first.tabs.filter(tab => tab.kind === 'guest')).toHaveLength(2);
  expect(first.tabs.filter(tab => tab.kind === 'shared')).toHaveLength(1);
  const common = first.tabs.find(tab => tab.kind === 'shared');
  expect(common.present).toBe(false);
  await add('Testgericht');
  await chip('Gast 2').click(); await add('Wasser'); await undo().click();
  await expect(composer().locator('.fp-cart-line')).toHaveCount(1);
  await add('Wasser');
  await write(() => composer().getByRole('button', { name: 'Gast hinzufügen', exact: true }).click(), '/guest-tabs');
  await expect(chip('Gast 3')).toHaveAttribute('aria-pressed', 'true');
  await add('Wasser');
  await chip('Gemeinsam').click(); await add('Gemeinsame Flasche');
  await composer().getByLabel('Notiz für diese Runde', { exact: true }).fill('Gemeinsam bestellt, getrennt kassierbar.');
  await expect(composer().locator('.fp-cart-line')).toHaveCount(4);
  await t.shot('eine-runde-mit-gastchips-und-gemeinsamer-flasche');

  const payloads = await t.loseFirstAnswer(`**/api/gastro/venues/*/service-visits/${first.id}/rounds`, true);
  await write(() => composer().getByRole('button', { name: 'Runde senden', exact: true }).click(), '/rounds', 503);
  await expect(undo()).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Neuer Besuch', exact: true })).toBeDisabled();
  await page.reload(); await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await nav('Bestellungen'); await page.getByRole('button', { name: 'Gäste & Runden', exact: true }).click();
  await expect(undo()).toBeDisabled();
  await write(() => composer().getByRole('button', { name: 'Bestellung erneut prüfen', exact: true }).click(), '/rounds', 409);
  const sent = await write(() => composer().getByRole('button', { name: 'Bestellung erneut prüfen', exact: true }).click(), '/rounds');
  expect(payloads).toHaveLength(3); expect(payloads[1]).toEqual(payloads[0]); expect(payloads[2]).toEqual(payloads[0]);
  expect(sent.children).toHaveLength(4);
  expect(new Set(sent.children.map(child => child.order_id)).size).toBe(4);
  expect(sent.children.reduce((sum, child) => sum + child.order.total_cents, 0)).toBe(2601);
  await expect(composer().locator('.fp-cart-line')).toHaveCount(0);
  await expect(undo()).toBeDisabled();
  report.checks.push('Zwei gleiche Getränke für verschiedene Gäste bleiben getrennt; Shared zählt nicht als Person. Ein Sendebefehl erzeugt vier unabhängige Originalbons. Commit503, Reload,409 und identischer Retry erzeugen keine zweite Runde.');

  const second = await createVisit('Unabhängiger Gast', 1);
  expect(second.id).not.toBe(first.id);
  expect(second.tabs[0].current_table_id).toBe(first.tabs[0].current_table_id);
  await page.getByRole('button', { name: 'Alle Besuche', exact: true }).click();
  await expect(page.getByRole('button', { name: /Freunde am Fenster/ })).toBeVisible();
  await expect(page.getByRole('button', { name: /Unabhängiger Gast/ })).toBeVisible();
  await t.shot('unabhaengige-besuche-am-selben-tisch');
  await page.getByRole('button', { name: /Freunde am Fenster/ }).click();
  await page.locator('summary').filter({ hasText: 'Gäste, Namen & Plätze' }).click();
  await page.getByRole('button', { name: 'Gast 3 bearbeiten', exact: true }).click();
  const newPlace = modal().getByLabel('Tisch (optional)', { exact: true });
  await newPlace.selectOption(await newPlace.locator('option').filter({ hasText: /^T02$/ }).getAttribute('value'));
  await modal().getByLabel('Grund der Änderung', { exact: true }).fill('Gast möchte am ruhigeren Tisch sitzen.');
  await write(() => modal().getByRole('button', { name: 'Gastangaben speichern', exact: true }).click(), '/context');
  await expect(modal()).toHaveCount(0);
  await chip('Gast 1').click(); await add('Wasser');
  await chip('Gast 3').click();
  await expect(undo()).toBeEnabled(); await undo().click();
  await expect(composer().locator('.fp-cart-line')).toHaveCount(0);
  report.checks.push('Unabhängiger Besuch teilt T01 ausdrücklich. Gast3 wechselt nach T02; Gastwechsel zwischen Tischen innerhalb derselben Runde bewahrt das lokale Rückgängig.');

  await nav('Küche & Bar');
  const thirdChild = sent.children.find(child => child.label_snapshot === 'Gast 3');
  expect(thirdChild).toBeTruthy();
  await expect(ticket(thirdChild.number)).toContainText('T02');
  await t.shot('kueche-zeigt-aktuellen-gastort-der-runde');
  await visitMode();
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 740 });
    await chip('Gemeinsam').click();
    await add('Gemeinsame Flasche');
    await expect(undo()).toBeInViewport();
    const area = await undo().boundingBox();
    expect(area.height).toBeGreaterThanOrEqual(44); expect(area.width).toBeGreaterThanOrEqual(44);
    await t.shot(`gast-runde-mobile-${width}`);
    await undo().click();
  }
  report.checks.push('Küche zeigt T02 als aktuellen Ausgabeort. Mobile Gästeauswahl und direktes44px-Rückgängig bei390/320px ohne Axe-Verstöße oder horizontalen Überlauf.');
} catch (error) { failure = error; }
await t.finish(failure);
