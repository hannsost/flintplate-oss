import { acceptance, expect } from './flintplate-acceptance-runner.mjs';

// Only the final send/retry reaches the isolated API. Undo never mutates a
// submitted receipt, payment or cancellation. All edits use visible controls.
const t = await acceptance('flintplate-order-undo-acceptance');
const { page, context, nav, modal, write, report } = t;
const undo = () => page.getByRole('button', { name: 'Rückgängig', exact: true });
const line = name => page.locator('.fp-cart-line').filter({ has: page.getByText(name, { exact: true }) });
const note = () => page.getByLabel('Hinweis zur Bestellung', { exact: true });
const table = () => page.getByLabel('Tisch oder Aktivität', { exact: true });
const add = name => page.getByRole('button', { name: `${name} hinzufügen`, exact: true }).click();
const logout = async () => { await page.getByRole('button', { name: 'Abmelden', exact: true }).first().click(); await page.waitForURL('**/anmelden*'); };
let failure, other;
try {
  await t.login('worker'); await nav('Bestellungen');
  const t01 = await table().locator('option').filter({ hasText: /^T01/ }).getAttribute('value');
  const t02 = await table().locator('option').filter({ hasText: /^T02/ }).getAttribute('value');
  await table().selectOption(t01); await expect(undo()).toBeDisabled();
  await add('Testgericht'); await expect(line('Testgericht')).toHaveCount(1); await expect(undo()).toBeEnabled();
  await undo().click(); await expect(page.locator('.fp-cart-line')).toHaveCount(0); await expect(undo()).toBeDisabled();
  await add('Testgericht'); await line('Testgericht').getByRole('button', { name: 'Testgericht mehr', exact: true }).click();
  await expect(line('Testgericht').locator('.fp-quantity>span')).toHaveText('2'); await undo().click(); await expect(line('Testgericht').locator('.fp-quantity>span')).toHaveText('1');
  await line('Testgericht').getByRole('button', { name: 'Testgericht weniger', exact: true }).click();
  await expect(line('Testgericht')).toHaveCount(0); await undo().click(); await expect(line('Testgericht')).toHaveCount(1);
  await page.getByLabel('Gang für Testgericht', { exact: true }).selectOption('2'); await undo().click(); await expect(page.getByLabel('Gang für Testgericht', { exact: true })).toHaveValue('1');
  await note().focus(); await note().pressSequentially('ohne Zwiebeln'); await undo().click(); await expect(note()).toHaveValue('');
  await note().fill('Lokal geprüfter Hinweis'); await add('Wasser');
  await page.getByRole('button', { name: 'Entwurf verwerfen', exact: true }).click(); await page.getByRole('button', { name: 'Entwurf leeren', exact: true }).click();
  await expect(page.locator('.fp-cart-line')).toHaveCount(0); await expect(note()).toHaveValue(''); await undo().click();
  await expect(page.locator('.fp-cart-line')).toHaveCount(2); await expect(note()).toHaveValue('Lokal geprüfter Hinweis');
  await t.shot('lokale-auswahl-menge-gang-notiz-rueckgaengig');
  report.checks.push('Sichtbare Rückgängig-Taste nimmt Hinzufügen, Menge, Entfernen, Gang, zusammenhängende Notizeingabe und Entwurf leeren zurück.');

  await table().selectOption(t02); await expect(undo()).toBeDisabled(); await expect(page.locator('.fp-cart-line')).toHaveCount(0);
  await add('Wasser'); await expect(undo()).toBeEnabled();
  await table().selectOption(t01); await expect(undo()).toBeDisabled(); await expect(note()).toHaveValue('Lokal geprüfter Hinweis');
  await page.getByRole('button', { name: 'To go', exact: true }).click(); await expect(undo()).toBeDisabled(); await expect(page.locator('.fp-cart-line')).toHaveCount(0);
  await add('Wasser'); await expect(undo()).toBeEnabled();
  await page.getByRole('button', { name: 'Vor Ort', exact: true }).click(); await table().selectOption(t01); await expect(undo()).toBeDisabled();
  await line('Wasser').getByRole('button', { name: 'Wasser mehr', exact: true }).click(); await expect(undo()).toBeEnabled();
  other = await context.newPage(); other.on('pageerror', error => report.errors.push(error.message));
  await other.goto(`${report.baseUrl}/gastro`); await other.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' });
  await other.getByRole('navigation', { name: 'Betriebsnavigation' }).getByRole('button', { name: 'Bestellungen', exact: false }).click();
  await other.getByLabel('Tisch oder Aktivität', { exact: true }).selectOption(t01);
  await other.getByLabel('Hinweis zur Bestellung', { exact: true }).fill('Änderung aus zweitem Browser-Tab');
  await expect(note()).toHaveValue('Änderung aus zweitem Browser-Tab'); await expect(undo()).toBeDisabled(); await other.close(); other = undefined;
  expect(report.networkWrites.filter(row => /\/orders(?:\/[^/]+\/append)?$/.test(row.path))).toHaveLength(0);
  report.checks.push('Zielwechsel T01/T02/To go und echte Fremdtab-Bearbeitung verwerfen den alten Undo-Verlauf; getrennte Entwürfe bleiben erhalten. Bis hier kein Bestell-POST.');

  await logout(); await t.login(); await nav('Bestellungen'); await table().selectOption(t01);
  await expect(page.locator('.fp-cart-line')).toHaveCount(0); await expect(note()).toHaveValue(''); await expect(undo()).toBeDisabled(); await add('Testgericht');
  const payloads = await t.loseFirstAnswer('**/api/gastro/venues/*/orders', true);
  await write(() => page.getByRole('button', { name: 'An Küche & Bar senden', exact: true }).click(), '/orders', 503);
  await expect(undo()).toBeDisabled(); await expect(note()).toBeDisabled();
  await page.reload(); await page.getByText('FlintPlate wird geladen …', { exact: false }).waitFor({ state: 'hidden' }); await nav('Bestellungen'); await expect(undo()).toBeDisabled();
  await write(() => page.getByRole('button', { name: 'Bestellung erneut prüfen', exact: true }).click(), '/orders', 409); await expect(undo()).toBeDisabled();
  const sent = await write(() => page.getByRole('button', { name: 'Bestellung erneut prüfen', exact: true }).click(), '/orders');
  expect(payloads).toHaveLength(3); expect(payloads[1]).toEqual(payloads[0]); expect(payloads[2]).toEqual(payloads[0]);
  await expect(page.locator('.fp-cart-line')).toHaveCount(0); await expect(undo()).toBeDisabled(); await expect(page.locator('.fp-kitchen-ticket').filter({ hasText: sent.number })).toBeVisible();
  report.checks.push('Kontowechsel übernimmt keine Drafts/History. Commit503, Reload und weiterer409 lassen Undo gesperrt; identischer Retry bestätigt denselben Bon und leert den Verlauf.');

  await page.setViewportSize({ width: 390, height: 844 }); await add('Wasser');
  await expect(modal()).toHaveCount(0); await expect(undo()).toBeInViewport(); await expect(undo()).toBeEnabled();
  const quick = await undo().boundingBox(); expect(quick.height).toBeGreaterThanOrEqual(44); expect(quick.width).toBeGreaterThanOrEqual(44);
  await t.shot('rueckgaengig-direkt-am-mobilen-warenkorb'); await undo().click();
  await expect(page.getByRole('status').filter({ hasText: 'Letzte Änderung rückgängig gemacht.' })).toBeVisible(); await expect(page.getByRole('button', { name: /Warenkorb öffnen · 0/ })).toBeVisible();
  await add('Wasser'); await page.getByRole('button', { name: /Warenkorb öffnen/ }).click();
  await expect(undo()).toHaveCount(1); await expect(modal().getByRole('button', { name: 'Rückgängig', exact: true })).toBeEnabled();
  await modal().getByRole('button', { name: 'Rückgängig', exact: true }).click(); await expect(modal().locator('.fp-cart-line')).toHaveCount(0);
  await t.shot('rueckgaengig-im-mobilen-warenkorb'); await modal().getByRole('button', { name: 'Dialog schließen', exact: true }).click();
  await page.setViewportSize({ width: 320, height: 740 }); await add('Wasser'); await expect(undo()).toBeInViewport(); await t.shot('rueckgaengig-schmale-320px-ansicht'); await undo().click();
  expect(payloads).toHaveLength(3); await expect(page.locator('.fp-kitchen-ticket').filter({ hasText: sent.number })).toHaveCount(1);
  report.checks.push('Mobile Direkt-Taste 44px mit Statushinweis; im offenen Modal nur innere Taste. 390px/320px Axe und Overflow; gesendeter Bon bleibt vorhanden.');
} catch (error) { failure = error; }
await other?.close(); await t.finish(failure);
