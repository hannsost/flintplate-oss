import { acceptance, expect } from './flintplate-acceptance-runner.mjs';
// Execute only after schema082 + coordinated UI build. All writes use visible UI controls.
const t = await acceptance('flintplate-floorplan-acceptance');
const { page, modal, nav, write, shot, report } = t;
const profileName = `Abendservice ${Date.now().toString(36)}`;
const resource = () => page.locator('.fp-floorplan').getByRole('button', { name: /^T01,/ });
const profile = () => modal().locator('article').filter({ has: page.getByRole('heading', { name: profileName, exact: true }) });
let failure;
let releaseRefresh;
async function expectOnVisibleGrid() {
  const grid = await resource().evaluate(button => {
    const board = button.closest('.fp-floorplan'), style = getComputedStyle(board), rect = board.getBoundingClientRect(), item = button.getBoundingClientRect();
    const step = style.backgroundSize.split(' ').map(parseFloat), origin = style.backgroundPosition.split(' ').map(parseFloat);
    const first = [origin[0] + step[0] / 2, origin[1] + step[1] / 2];
    const distance = (value, dot, spacing) => { const remainder = ((value - dot) % spacing + spacing) % spacing; return Math.min(remainder, spacing - remainder); };
    return { step, first, image: style.backgroundImage, dx: distance(item.left - rect.left, first[0], step[0]), dy: distance(item.top - rect.top, first[1], step[1]) };
  });
  expect(grid.step).toEqual([16, 16]); expect(grid.first).toEqual([22, 58]); expect(grid.image).toContain('at 8px 8px'); expect(grid.dx).toBeLessThan(1); expect(grid.dy).toBeLessThan(1);
}
async function move(dx, dy, status = 201) {
  await expect(page.getByLabel('Am Raster ausrichten')).toBeEnabled();
  const before = await resource().boundingBox();
  await page.mouse.move(before.x + before.width - 12, before.y + before.height - 10); await page.mouse.down();
  await page.mouse.move(before.x + before.width - 12 + dx, before.y + before.height - 10 + dy, { steps: 6 });
  await expect(resource()).toContainText('Hier ablegen'); await expectOnVisibleGrid(); const ghost = await resource().boundingBox();
  const result = await write(() => page.mouse.up(), '/position', status);
  if (status < 300) { await expect.poll(async () => (await resource().boundingBox()).x).toBeCloseTo(ghost.x, 0); await expect.poll(async () => (await resource().boundingBox()).y).toBeCloseTo(ghost.y, 0); }
  await expect(modal()).toHaveCount(0); return { before, result };
}
try {
  await t.login();
  if (new URL(report.baseUrl).hostname === '192.168.0.160') { expect(await page.evaluate(() => isSecureContext)).toBe(false); expect(await page.evaluate(() => typeof crypto.randomUUID)).toBe('undefined'); }
  await nav('Räume & Aktivitäten'); await resource().scrollIntoViewIfNeeded();
  await resource().click(); await expect(modal()).toHaveAttribute('aria-label', 'T01'); await modal().getByRole('button', { name: 'Dialog schließen', exact: true }).click();
  await page.getByRole('button', { name: 'Anordnung bearbeiten', exact: true }).click();
  await expect(page.getByLabel('Am Raster ausrichten')).toBeChecked(); await page.getByLabel('Am Raster ausrichten').uncheck(); await expect(page.getByLabel('Am Raster ausrichten')).not.toBeChecked(); await page.getByLabel('Am Raster ausrichten').check();
  const first = await move(72, 40); expect(first.result.x).toBeGreaterThanOrEqual(0); await shot('grundriss-position-sichtbar-gespeichert');
  // A definite server rejection must roll the visual position back and allow a new edit.
  await page.route('**/api/gastro/venues/*/tables/*/position', route => route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: 'Isolierte Prüfung: Position zwischenzeitlich geändert.' }) }), { times: 1 });
  const rejected = await move(38, 20, 409); await expect.poll(async () => (await resource().boundingBox()).x).toBeCloseTo(rejected.before.x, 0); await expect(page.getByRole('alert').filter({ hasText: 'zwischenzeitlich geändert' })).toBeVisible();
  await page.getByRole('button', { name: 'Grundrissprofile', exact: true }).click(); await modal().getByRole('button', { name: 'Aktuelle Anordnung speichern', exact: true }).click(); await modal().getByLabel('Profilname').fill(profileName); const saved = await write(() => modal().getByRole('button', { name: 'Profil verbindlich speichern', exact: true }).click(), '/layout/profiles'); await expect(profile()).toContainText('Version 1'); await modal().getByRole('button', { name: 'Dialog schließen', exact: true }).click();
  const payloads = await t.loseFirstAnswer('**/api/gastro/venues/*/tables/*/position'); await move(40, 16, 503); await page.reload(); await nav('Räume & Aktivitäten'); await write(() => page.getByRole('button', { name: 'Grundrissvorgang erneut prüfen', exact: true }).click(), '/position'); expect(payloads).toHaveLength(2); expect(payloads[1]).toEqual(payloads[0]);
  await page.getByRole('button', { name: 'Grundrissprofile', exact: true }).click(); await profile().getByRole('button', { name: 'Vorschau', exact: true }).click(); await expect(modal()).toContainText('1 Positionen ändern sich'); await shot('grundrissprofil-vorschau');
  // A successful POST must not expose stale versions while its authoritative
  // read is still in flight. Hold real reads; do not fabricate table versions.
  const refreshGate = new Promise(resolve => { releaseRefresh = resolve; });
  let holdRefresh = true;
  const holdTables = async route => { if (holdRefresh && route.request().method() === 'GET') await refreshGate; await route.fallback(); };
  await page.route('**/api/gastro/venues/*/tables', holdTables);
  const applied = await write(() => modal().getByRole('button', { name: 'Diese Anordnung anwenden', exact: true }).click(), '/apply');
  expect(applied.profile_id).toBe(saved.id);
  await modal().getByRole('button', { name: 'Dialog schließen', exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 }); await resource().scrollIntoViewIfNeeded();
  await expect(page.getByRole('button', { name: 'Anordnung bearbeiten', exact: true })).toBeDisabled();
  await expect(page.getByRole('status').filter({ hasText: 'Grundriss wird aktualisiert.' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Grundrissvorgang erneut prüfen', exact: true })).toBeDisabled();
  await page.getByRole('status').filter({ hasText: 'Grundriss wird aktualisiert.' }).scrollIntoViewIfNeeded();
  await shot('grundriss-profil-nachladung-sichtbar-gesperrt');
  holdRefresh = false; releaseRefresh(); await page.unroute('**/api/gastro/venues/*/tables', holdTables);
  await expect(page.getByRole('button', { name: 'Anordnung bearbeiten', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Anordnung bearbeiten', exact: true }).click();
  await resource().scrollIntoViewIfNeeded();
  // Chromium's actual touch input generates pointer events; no DOM-dispatched fake events.
  const cdp = await t.context.newCDPSession(page); await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: true, maxTouchPoints: 1 });
  const box = await resource().boundingBox(), point = { x: box.x + 20, y: box.y + 25 };
  await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [point] }); await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: point.x + 24, y: point.y + 20 }] }); await expect(resource()).toContainText('Hier ablegen'); await expectOnVisibleGrid(); await shot('grundriss-ziehen-touch-zielvorschau');
  await write(async () => {
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] }); await expect(modal()).toHaveCount(0);
    // No delay and no wait for the API response: the next pointer sequence must work.
    const tap = await resource().boundingBox(); await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [{ x: tap.x + 20, y: tap.y + 20 }] }); await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] }); await expect(modal()).toHaveAttribute('aria-label', 'T01');
  }, '/position');
  await modal().getByRole('button', { name: 'Dialog schließen', exact: true }).click(); await cdp.detach();
  await page.getByRole('button', { name: 'Grundrissprofile', exact: true }).click(); await profile().getByRole('button', { name: 'Aktuelle Anordnung als neue Version', exact: true }).click(); await write(() => modal().getByRole('button', { name: 'Profil verbindlich speichern', exact: true }).click(), '/layout/profiles'); await profile().getByRole('button', { name: 'Versionshistorie', exact: true }).click(); await expect(profile()).toContainText('Version 1'); await expect(profile()).toContainText('Version 2'); await shot('grundrissprofile-mobil-versionen');
  report.checks.push('Raster ist standardmäßig aktiv und abschaltbar; Maus-/Touch-Liveziele liegen auf den tatsächlich gerenderten Gridpunkten. Maus-Griffpunkt und Live-Ziel stimmen mit gespeicherter Position überein; Tap öffnet Details.409 zeigt Rollback, Commit503/Reload wird identisch wiederholt. Profil-Apply hält bei verzögerter echter Nachladung Bearbeiten und Retry auch nach sofortigem Dialogschließen sichtbar gesperrt. Danach gelingt der Touchdrag mit aktueller Version und sofort folgendem Tap. Benanntes Profil wird vor Anwendung gezeigt; alte Profilversionen bleiben sichtbar.');
} catch (error) { failure = error; }
finally { releaseRefresh?.(); }
await t.finish(failure);
