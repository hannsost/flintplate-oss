import { acceptance, expect } from './flintplate-acceptance-runner.mjs';

// Runs after the round journey against its synthetic visit. Changes only the
// local, unsent cart; it never creates an order or changes a financial record.
const t = await acceptance('flintplate-guest-mobile-acceptance');
const { page } = t;
let failure;
try {
  await t.login();
  await t.nav('Bestellungen');
  await page.getByRole('button', { name: 'Gäste & Runden', exact: true }).click();
  await page.getByRole('button', { name: /Freunde am Fenster/ }).click();
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 740 });
    const guests = page.getByLabel('Gäste dieser Runde', { exact: true });
    await guests.getByRole('button', { name: 'Gast 1', exact: true }).click();
    await guests.scrollIntoViewIfNeeded();
    await t.shot(`gast-auswahl-${width}`);
    await guests.getByRole('button', { name: 'Gemeinsam', exact: true }).click();
    await page.getByRole('button', { name: 'Gemeinsame Flasche hinzufügen', exact: true }).click();
    await page.getByRole('button', { name: /Warenkorb öffnen · 1/ }).click();
    const cart = t.modal();
    await expect(cart).toContainText('Gemeinsam');
    await expect(cart).toContainText('10,01');
    await t.shot(`gast-warenkorb-${width}`);
    await cart.getByRole('button', { name: 'Rückgängig', exact: true }).click();
    await expect(cart.locator('.fp-cart-line')).toHaveCount(0);
    await cart.getByRole('button', { name: 'Dialog schließen', exact: true }).click();
  }
  expect(t.report.networkWrites.filter(row => !row.path.endsWith('/suggestions'))).toHaveLength(0);
  t.report.checks.push('Gastchips und gemeinsamer Warenkorb bei390/320px sichtbar bedient und visuell aufgenommen; Undo leert nur den lokalen Entwurf. Keine Geschäfts- oder Zahlungswrites, Axe und Overflow grün.');
} catch (error) { failure = error; }
await t.finish(failure);
