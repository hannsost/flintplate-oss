import path from 'node:path';
import { pathToFileURL } from 'node:url';

// Run from the existing FlintPlate frontend directory. Reuses its current runner
// and strictly isolated socket proxy; no copied runner, API setup or real data.
const { acceptance, expect } = await import(pathToFileURL(path.resolve('e2e/flintplate-acceptance-runner.mjs')).href);
const t = await acceptance('flintplate-tasks-086-acceptance');
const { page, modal, nav, write, report } = t;
const tag = Date.now().toString(36);
const names = { routine: `Tische abwischen ${tag}`, note: `Servicestation auffüllen ${tag}`, foreign: `Küchenübergabe ${tag}` };
const card = task => page.locator(`[data-task-id="${task.id}"]`);
const date = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
const logout = async () => { await page.getByRole('button', { name: 'Abmelden', exact: true }).first().click(); await page.waitForURL('**/anmelden*'); };
const close = async () => { await expect(modal().getByRole('button', { name: 'Dialog schließen', exact: true })).toBeEnabled(); await modal().getByRole('button', { name: 'Dialog schließen', exact: true }).click(); await expect(modal()).toHaveCount(0); };
const archive = () => page.getByLabel('Auch erledigte und abgebrochene', { exact: true });
async function readClick(click, suffix) {
  const [response] = await Promise.all([page.waitForResponse(response => response.request().method() === 'GET' && new URL(response.url()).pathname.endsWith(suffix)), click()]);
  expect(response.status()).toBe(200);
  return response.json();
}
async function createTask(title, person, requireNote = false) {
  await expect(page.getByRole('button', { name: 'Aufgabe zuweisen', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Aufgabe zuweisen', exact: true }).click();
  await modal().getByLabel('Zuständige Person', { exact: true }).selectOption({ label: person });
  await modal().getByLabel('Aufgabe', { exact: true }).fill(title);
  await modal().getByLabel('Notiz / Arbeitsanweisung', { exact: true }).fill('Synthetischer Arbeitsauftrag für die isolierte Browserabnahme.');
  await modal().getByLabel('Priorität', { exact: true }).selectOption(requireNote ? 'high' : 'medium');
  await modal().getByLabel(/^Fällig \(/).fill(`${date}T16:30`);
  await expect(modal().getByLabel('Abschlussnotiz erforderlich', { exact: true })).not.toBeChecked();
  if (requireNote) await modal().getByLabel('Abschlussnotiz erforderlich', { exact: true }).check();
  const task = await write(() => modal().getByRole('button', { name: 'Aufgabe verbindlich zuweisen', exact: true }).click(), '/tasks');
  expect(task.title).toBe(title); expect(task.status).toBe('open'); expect(task.version).toBe(1); expect(task.require_completion_note).toBe(requireNote);
  await expect(modal()).toHaveCount(0); // Wait for authoritative refresh, not just POST201.
  await expect(card(task)).toContainText(person);
  return task;
}
async function teamTasks() {
  return readClick(() => page.getByRole('navigation', { name: 'Team-Navigation' }).getByRole('button', { name: 'Meine Aufgaben', exact: true }).click(), '/tasks');
}
async function history(task) {
  const result = await readClick(() => card(task).getByRole('button', { name: 'Details & Verlauf', exact: true }).click(), `/tasks/${task.id}/history`);
  await expect(modal().getByText('FlintPlate wird geladen …', { exact: false })).toHaveCount(0);
  expect(result.items.every(command => command.task_id === task.id)).toBe(true);
  return result.items;
}
let failure;
try {
  await t.login(); await nav('Aufgaben');
  const routine = await createTask(names.routine, 'Test Service');
  const required = await createTask(names.note, 'Test Service', true);
  const foreign = await createTask(names.foreign, 'Test Küche');
  expect(routine.assigned_to).toBe(required.assigned_to); expect(foreign.assigned_to).not.toBe(routine.assigned_to);
  await expect(page.getByRole('button', { name: 'Aufgabe zuweisen', exact: true })).toBeEnabled();
  await t.shot('leitung-drei-zuweisungen');
  report.checks.push('Leitung weist aus aktiven Betriebsmitgliedern drei Aufgaben zu. Abschlussnotiz ist standardmäßig aus und wird nur für die Servicestation ausdrücklich aktiviert.');

  await logout(); await t.login('worker');
  await page.getByRole('link', { name: 'Meine Team-App', exact: false }).click();
  await page.waitForURL('**/team');
  const mine = await teamTasks();
  expect(mine.items.every(task => task.assigned_to === routine.assigned_to)).toBe(true);
  expect(mine.items.map(task => task.id)).toEqual(expect.arrayContaining([routine.id, required.id]));
  expect(mine.items.some(task => task.id === foreign.id)).toBe(false);
  await expect(card(routine)).toBeVisible(); await expect(card(required)).toBeVisible(); await expect(card(foreign)).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Aufgabe zuweisen', exact: true })).toHaveCount(0);
  await expect(page.getByLabel('Nur meine Aufgaben', { exact: true })).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  await card(routine).scrollIntoViewIfNeeded(); await t.shot('mitarbeiter-eigene-aufgaben-mobil');
  report.checks.push('Mitarbeiter öffnet die Team-App über die sichtbare Navigation. API-Antwort und Oberfläche enthalten nur eigene Aufgaben, keine Küchenaufgabe und keine Zuweisungsaktion.');

  const payloads = await t.loseFirstAnswer(`**/api/gastro/venues/*/tasks/${routine.id}/action`, true);
  await expect(card(routine).getByRole('button', { name: 'Erledigen', exact: true })).toBeEnabled();
  // Exactly one click from open -> done. The first committed answer is lost.
  await write(() => card(routine).getByRole('button', { name: 'Erledigen', exact: true }).click(), `/tasks/${routine.id}/action`, 503);
  await expect(modal()).toHaveCount(0);
  expect(payloads).toHaveLength(1); expect(payloads[0].action).toBe('done'); expect(payloads[0].version).toBe(routine.version); expect(payloads[0].note).toBe('Aufgabe erledigt');
  await expect(page.getByRole('button', { name: 'Aufgabenvorgang erneut prüfen', exact: true })).toBeEnabled();
  await page.reload(); await page.getByRole('navigation', { name: 'Team-Navigation' }).waitFor(); await teamTasks();
  const retry = page.getByRole('button', { name: 'Aufgabenvorgang erneut prüfen', exact: true });
  await expect(retry).toBeEnabled();
  await expect(card(required).getByRole('button', { name: 'Erledigen', exact: true })).toBeDisabled();
  await write(() => retry.click(), `/tasks/${routine.id}/action`, 409);
  await expect(retry).toBeEnabled();
  const completed = await write(() => retry.click(), `/tasks/${routine.id}/action`);
  expect(completed.status).toBe('done'); expect(completed.version).toBe(routine.version + 1); expect(completed.completed_at).toBeTruthy(); expect(completed.assigned_to).toBe(routine.assigned_to);
  expect(payloads).toHaveLength(3); expect(payloads[1]).toEqual(payloads[0]); expect(payloads[2]).toEqual(payloads[0]);
  await expect(retry).toHaveCount(0); await expect(card(routine)).toHaveCount(0);
  await expect(archive()).toBeEnabled(); await archive().check();
  await expect(card(routine)).toHaveCount(1); await expect(card(routine)).toContainText('Erledigt');
  await expect(card(routine).getByRole('button', { name: 'Erledigen', exact: true })).toHaveCount(0);
  await expect(card(required).getByRole('button', { name: 'Erledigen', exact: true })).toBeEnabled();
  await card(routine).scrollIntoViewIfNeeded(); await t.shot('routine-erledigt-identischer-retry-mobil');
  report.checks.push('Routineabschluss aus offen mit einem Klick, ohne Pflichtdialog. Commit503, Reload und weiterer409 behalten exakt Payload/Key; Retry liefert einmalig Version2. Während Klärung sind weitere Mutationen gesperrt; erledigte Aufgabe bleibt auffindbar.');

  await card(required).getByRole('button', { name: 'Erledigen', exact: true }).click();
  await expect(modal()).toBeVisible();
  const note = modal().getByLabel('Abschlussnotiz / Nachweis', { exact: true });
  await expect(note).toHaveValue(''); await expect(note).toHaveAttribute('required', '');
  const writesBefore = report.networkWrites.length;
  await modal().getByRole('button', { name: 'Erledigung mit Nachweis bestätigen', exact: true }).click();
  await expect(note).toBeFocused(); await expect(modal()).toBeVisible(); expect(report.networkWrites.length).toBe(writesBefore);
  await note.fill('Servicestation vollständig aufgefüllt und Materialbestand geprüft.');
  await page.keyboard.press('Tab');
  expect(await modal().evaluate(element => element.contains(document.activeElement))).toBe(true);
  await t.shot('ausdrueckliche-abschlussnotiz-mobil');
  const withNote = await write(() => modal().getByRole('button', { name: 'Erledigung mit Nachweis bestätigen', exact: true }).click(), `/tasks/${required.id}/action`);
  expect(withNote.status).toBe('done'); expect(withNote.version).toBe(required.version + 1); expect(withNote.worker_note).toBe('Servicestation vollständig aufgefüllt und Materialbestand geprüft.');
  await expect(modal()).toHaveCount(0); await expect(card(required)).toContainText(withNote.worker_note);
  await expect(card(foreign)).toHaveCount(0);
  report.checks.push('Ausdrücklich geforderte Abschlussnotiz wird nicht vorbelegt: leeres Absenden bleibt im Dialog ohne POST. Echter Notizabschluss ist aus offen möglich; mobile Tastaturführung, Axe und Overflow werden geprüft.');

  await logout(); await page.setViewportSize({ width: 1440, height: 1050 }); await t.login(); await nav('Aufgaben');
  await expect(card(foreign)).toContainText('Offen');
  await expect(archive()).toBeEnabled(); await archive().check();
  await expect(card(routine)).toContainText('Erledigt'); await expect(card(required)).toContainText('Erledigt');
  const routineHistory = await history(routine);
  expect(routineHistory).toHaveLength(2); expect(routineHistory.filter(command => command.kind === 'done')).toHaveLength(1);
  const finish = routineHistory.find(command => command.kind === 'done');
  expect(finish.actor_id).toBe(routine.assigned_to); expect(finish.actor_name).toBe('Test Service'); expect(finish.before.status).toBe('open'); expect(finish.after.status).toBe('done'); expect(finish.created_at).toBeTruthy();
  await expect(modal()).toContainText('Aufgabe erledigt'); await expect(modal()).toContainText('Test Service');
  await t.shot('leitung-routineabschluss-verlauf'); await close();
  const noteHistory = await history(required);
  expect(noteHistory).toHaveLength(2); expect(noteHistory.find(command => command.kind === 'done').note).toBe(withNote.worker_note);
  await expect(modal()).toContainText(withNote.worker_note);
  await t.shot('leitung-belegter-notizabschluss'); await close();
  report.checks.push('Leitung findet beide Abschlüsse samt handelnder Person, Zeitpunkt und gespeicherten Vor-/Nachständen. Routinehistorie enthält trotz dreier Übertragungen nur create+done; Küchenauftrag bleibt unverändert offen.');
} catch (error) { failure = error; }
await t.finish(failure);
