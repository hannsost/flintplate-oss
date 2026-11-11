import { chromium, expect as baseExpect } from '@playwright/test';
import fs from 'node:fs/promises';
const credentials=JSON.parse(await fs.readFile(new URL('../../backend/.local/demo-access.json',import.meta.url),'utf8'));
const root='/tmp/hireos-browser-tests/flintplate';
const browser=await chromium.launch({executablePath:'/tmp/palmscout-playwright/chromium_headless_shell-1243/chrome-headless-shell-linux64/chrome-headless-shell',headless:true,args:['--disable-gpu','--no-sandbox']});
const expect=baseExpect.configure({timeout:30000});
const steps=[],errors=[];
async function login(role,path){const context=await browser.newContext({viewport:{width:390,height:844},timezoneId:'Europe/Berlin'});const page=await context.newPage();page.setDefaultTimeout(60000);page.on('pageerror',e=>errors.push(e.message));await page.goto(`http://localhost:3012/anmelden?next=${encodeURIComponent(path)}`);await page.getByLabel('E-Mail-Adresse').fill(credentials[role]);await page.getByLabel('Passwort',{exact:true}).fill(credentials.password);await page.getByRole('button',{name:'Anmelden',exact:true}).click();await page.waitForURL(`**${path}`);await page.getByText("FlintPlate wird geladen …",{exact:false}).waitFor({state:"hidden"});return page;}
let current;
try{
  const team=current=await login('worker','/team');
  await team.getByRole('button',{name:'Arbeitszeit',exact:true}).click();
  if(await team.getByRole('button',{name:'Jetzt einstempeln'}).isVisible()){
    await team.getByRole('button',{name:'Jetzt einstempeln'}).click();
    await expect(team.getByText('Du bist eingestempelt.',{exact:true})).toBeVisible();
  }
  await team.reload();await team.getByRole('button',{name:'Arbeitszeit',exact:true}).click();
  await expect(team.getByText('Eingestempelt',{exact:true})).toBeVisible();
  steps.push('Einstempeln und Persistenz nach Reload bestätigt.');
  await team.getByLabel('Tatsächlich genommene Pause in Minuten').fill('0');
  await team.getByRole('button',{name:'Ausstempeln',exact:true}).click();
  await expect(team.getByRole('button',{name:'Einreichen',exact:true})).toBeVisible();
  await team.getByRole('button',{name:'Einreichen',exact:true}).click();
  await expect(team.getByText('Zeiteintrag zur Prüfung eingereicht.',{exact:true})).toBeVisible();
  await team.screenshot({path:`${root}/time-submitted-mobile.png`,fullPage:true});
  steps.push('Ausstempeln mit tatsächlicher Pause und Einreichen im persönlichen Bereich bestätigt.');
  const guest=current=await login('guest',`/kunden/${credentials.venue_id}`);
  await guest.getByRole('button',{name:'Reservieren',exact:true}).click();
  const options=await guest.getByLabel('Tisch oder Erlebnis').locator('option').evaluateAll(nodes=>nodes.map(n=>({value:n.value,text:n.textContent})));
  await guest.getByLabel('Tisch oder Erlebnis').selectOption(options.find(o=>o.text.startsWith('Tretboot 02')).value);
  const target=new Date();target.setUTCDate(target.getUTCDate()+12);const date=target.toISOString().slice(0,10);
  await guest.getByLabel('Name der Reservierung').fill('Synthetische Browsergruppe');
  await guest.getByLabel('Personen',{exact:true}).fill('2');
  await guest.getByLabel('Beginn (Ortszeit dieses Geräts)').fill(`${date}T13:00`);
  await guest.getByLabel('Ende (Ortszeit dieses Geräts)').fill(`${date}T14:00`);
  await guest.getByRole('button',{name:'Verbindlich reservieren'}).click();
  await expect(guest.getByText('Deine Reservierung wurde bestätigt.',{exact:true})).toBeVisible();
  await guest.getByRole('button',{name:'Verbindlich reservieren'}).click();
  await expect(guest.getByRole('alert').filter({hasText:/belegt|überschneidet|reserviert/})).toBeVisible();
  steps.push('Tretboot mobil reserviert; überlappende Doppelbuchung sichtbar abgewiesen.');
  await guest.reload();await guest.getByRole('button',{name:'Mein Besuch',exact:true}).click();
  await expect(guest.getByText('Tretboot 02 · 2 Personen',{exact:true})).toBeVisible();
  await expect(guest.getByText('Zitronen-Limo',{exact:false}).first()).toBeVisible();
  await guest.screenshot({path:`${root}/guest-order-mobile.png`,fullPage:true});
  steps.push('Bestellung und Reservierung nach Reload ausschließlich im eigenen Gastkonto sichtbar.');
  if(errors.length)throw new Error(JSON.stringify(errors));
  await fs.writeFile(`${root}/time-booking.json`,JSON.stringify({steps,errors},null,2));console.log(steps.join('\n'));
}catch(error){if(current)await current.screenshot({path:`${root}/time-booking-failure.png`,fullPage:true}).catch(()=>{});console.error(error.message.replaceAll(credentials.password,'[redacted]'));process.exitCode=1;}
finally{await browser.close();}
