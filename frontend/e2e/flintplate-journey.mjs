import { chromium, expect } from '@playwright/test';
import fs from 'node:fs/promises';

const credentials = JSON.parse(await fs.readFile(new URL('../../backend/.local/demo-access.json', import.meta.url), 'utf8'));
const root = '/tmp/hireos-browser-tests/flintplate';
const browser = await chromium.launch({ executablePath: '/tmp/palmscout-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell', headless: true, args: ['--disable-gpu', '--no-sandbox'] });
const errors = [], steps = [];
async function record(step) { steps.push(step); await fs.writeFile(`${root}/journey.json`, JSON.stringify({ steps, errors }, null, 2)); console.log(step); }
async function login(role, path, mobile = false) {
  const context = await browser.newContext({ viewport: mobile ? { width:390, height:844 } : { width:1440, height:1000 }, timezoneId:'Europe/Berlin' });
  const page = await context.newPage(); page.setDefaultTimeout(120000);
  page.on('pageerror', e => errors.push({ role, error:e.message }));
  page.on('response', r => { if (r.url().includes('/api/') && r.status() >= 500) errors.push({ role, status:r.status(), path:new URL(r.url()).pathname }); });
  await page.goto(`http://localhost:3012/anmelden?next=${encodeURIComponent(path)}`, { timeout:180000 });
  await page.getByLabel('E-Mail-Adresse').fill(credentials[role]);
  await page.getByLabel('Passwort', { exact:true }).fill(credentials.password);
  await page.getByRole('button', { name:'Anmelden', exact:true }).click();
  await page.waitForURL(`**${path}`, { timeout:180000 });
  await page.getByText('FlintPlate wird geladen …', { exact:false }).waitFor({ state:'hidden' });
  if (await page.getByRole('button', {name:'Erneut laden',exact:true}).isVisible()) {
    await page.getByRole('button', {name:'Erneut laden',exact:true}).click();
    await page.getByRole('button', {name:'Erneut laden',exact:true}).waitFor({state:'hidden'});
  }
  return page;
}
let current;
try {
  const manager = current = await login('manager', '/gastro');
  await manager.getByRole('button', { name:'Räume & Aktivitäten', exact:true }).click();
  await manager.getByLabel('Stockwerk', {exact:true}).selectOption({label:'Am Wasser'});
  await expect(manager.getByRole('button', {name:/Tretboot 01,/})).toBeVisible();
  await manager.screenshot({ path:`${root}/floor-water-desktop.png`, fullPage:true });
  await record('Stockwerk Am Wasser ausgewählt; Tretboote sichtbar.');

  const target = new Date(); target.setUTCDate(target.getUTCDate()+16);
  const isoDay = target.toISOString().slice(0,10), start = `${isoDay}T11:00`, end = `${isoDay}T17:00`;
  const station = `Service · Browser ${Date.now().toString().slice(-6)}`;
  await manager.getByRole('button', {name:'Team & Dienste',exact:true}).click();
  const prior=manager.locator('.fp-list-row').filter({hasText:'Service · Browser'}).getByRole('button',{name:'Absagen',exact:true});
  while(await prior.count()){const count=await prior.count();await prior.first().click();await expect(prior).toHaveCount(count-1);}
  await manager.getByRole('button', {name:'Dienst planen',exact:true}).click();
  const plan = manager.getByRole('dialog', {name:'Dienst planen'});
  await plan.getByLabel('Mitarbeitende', {exact:true}).selectOption({label:'Sam Berger · Service'});
  await plan.getByLabel('Station / Aufgabe').fill(station);
  await plan.getByLabel('Beginn (Gerätezeit)').fill(start);
  await plan.getByLabel('Ende (Gerätezeit)').fill(end);
  await plan.getByRole('button', {name:'Als Entwurf speichern'}).click();
  await plan.waitFor({state:'hidden'});
  const row = manager.locator('.fp-list-row').filter({hasText:station});
  await row.getByRole('button', {name:'Veröffentlichen',exact:true}).click();
  await expect(row.getByText('Veröffentlicht',{exact:true})).toBeVisible();
  await record('Leitung hat Dienst geplant und veröffentlicht.');

  const worker = current = await login('replacement','/team',true);
  await worker.getByRole('button',{name:'Mein Bereich',exact:true}).click();
  const optIn=worker.getByRole('checkbox',{name:'Ich möchte freiwillig Vertretungsanfragen erhalten.'});
  await expect(optIn).toBeEnabled();
  if (!(await optIn.isChecked())) await optIn.click();
  await expect(optIn).toBeChecked();
  await worker.getByLabel('Verfügbar ab (Gerätezeit)').fill(start);
  await worker.getByLabel('Verfügbar bis (Gerätezeit)').fill(end);
  await worker.getByRole('button',{name:'Zeitfenster anbieten',exact:true}).click();
  await expect(worker.getByRole('status').filter({hasText:'Zeitfenster angeboten.'})).toBeVisible();
  await worker.reload();
  await worker.getByRole('button',{name:'Mein Bereich',exact:true}).click();
  await expect(worker.getByRole('checkbox',{name:'Ich möchte freiwillig Vertretungsanfragen erhalten.'})).toBeChecked();
  await expect(worker.getByRole('button',{name:'Zurückziehen',exact:true}).first()).toBeVisible();
  await record('Team hat freiwillige Bereitschaft und Zeitfenster über Smartphone-Oberfläche gespeichert; nach Reload erhalten.');

  current = manager;
  await manager.getByRole('button',{name:'Vertretung suchen',exact:true}).click();
  const search = manager.getByRole('dialog',{name:'Vertretung suchen'});
  {
    const options = await search.getByLabel('Ausgefallener Dienst').locator('option').evaluateAll(nodes=>nodes.map(n=>({value:n.value,text:n.textContent})));
    await search.getByLabel('Ausgefallener Dienst').selectOption(options.find(o=>o.text.includes(station)).value);
  }
  await search.getByLabel('Grund der Suche (nur Leitung)').fill('Synthetischer Ausfall für Browserabnahme');
  await search.getByRole('button',{name:'Eignung & Reihenfolge prüfen'}).click();
  await expect(search.getByText('1. Jamie Kern',{exact:true})).toBeVisible();
  await manager.screenshot({path:`${root}/replacement-ranking-desktop.png`,fullPage:true});
  await search.getByRole('button',{name:'Verbindliche Anfragen jetzt starten'}).click();
  await search.waitFor({state:'hidden'});
  await record('Leitung hat begründete Rangfolge geprüft und sequentielle Anfrage gestartet.');

  current = worker;
  await worker.getByRole('button',{name:'Vertretungsanfragen aktualisieren'}).click();
  await expect(worker.getByRole('heading',{name:station,exact:true})).toBeVisible();
  await worker.screenshot({path:`${root}/replacement-offer-mobile.png`,fullPage:true});
  await worker.getByRole('button',{name:'Dienst übernehmen',exact:true}).click();
  await expect(worker.getByRole('status').filter({hasText:'Dienst übernommen.'})).toBeVisible();
  await worker.getByRole('button',{name:'Meine Dienste',exact:true}).click();
  await expect(worker.getByText(station,{exact:true})).toBeVisible();
  await worker.reload();
  await expect(worker.getByText(station,{exact:true})).toBeVisible();
  await worker.screenshot({path:`${root}/replacement-confirmed-mobile.png`,fullPage:true});
  await record('Vertretung verbindlich angenommen; neuer Dienst im persönlichen Plan und nach Reload sichtbar.');

  current = manager;
  await manager.reload();
  await manager.getByRole('button',{name:'Team & Dienste',exact:true}).click();
  await expect(manager.getByText('Vertretung gefunden',{exact:true}).first()).toBeVisible();
  await expect(manager.locator('.fp-list-row').filter({hasText:station}).filter({hasText:'Jamie Kern'}).getByText('Veröffentlicht',{exact:true})).toBeVisible();
  await record('Leitung sieht besetzte Suche und veröffentlichten Ersatzdienst.');

  const guest = current = await login('guest',`/kunden/${credentials.venue_id}`,true);
  await guest.getByRole('button',{name:'Zitronen-Limo hinzufügen'}).click();
  await expect(guest.locator('.fp-total')).toContainText('6,90');
  await guest.getByLabel('Hinweis zur Bestellung').fill(`Browserabnahme ${station}`);
  await guest.getByRole('button',{name:'Zur Abholung bestellen'}).click();
  await expect(guest.getByText(/ist eingegangen. Bezahlt wird bei der Abholung./)).toBeVisible();

  await guest.reload();
  await guest.getByRole('button',{name:'Mein Besuch',exact:true}).click();
  await expect(guest.getByText('Zitronen-Limo',{exact:false}).first()).toBeVisible();
  await guest.screenshot({path:`${root}/guest-order-mobile.png`,fullPage:true});
  await record('Gast bestellt mobil inklusive Becherpfand; eigener Auftrag bleibt nach Reload sichtbar.');
  if (errors.length) throw new Error(JSON.stringify(errors));
  await record('Browserablauf ohne JavaScript-Fehler oder API-5xx abgeschlossen.');
} catch(error) {
  if (current && !current.isClosed()) await current.screenshot({path:`${root}/journey-failure.png`,fullPage:true}).catch(()=>{});
  console.error(error.message.replaceAll(credentials.password,'[redacted]'));
  process.exitCode=1;
} finally { await browser.close(); }
