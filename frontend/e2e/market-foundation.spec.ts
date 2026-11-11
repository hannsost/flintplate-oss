import { test, expect, type APIRequestContext, type Locator, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdirSync } from "node:fs";
const api = "http://localhost:8001";
const password = "SyntheticOnly123!";
const captures = "/tmp/hireos-browser-tests/palmscout-market";
const testLogo = "https://branding.example.test/logo.svg";
const logoSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="240" height="80"><rect width="240" height="80" rx="12" fill="#172554"/><circle cx="120" cy="40" r="26" fill="#ffff00"/></svg>';
async function signup(request: APIRequestContext, name: string, marker: number) {
  const email = `${name}-${marker}@example.com`;
  const response = await request.post(`${api}/auth/register`, { data: { email, password, full_name: name } });
  expect(response.ok(), await response.text()).toBeTruthy();
  const headers = { Authorization: `Bearer ${(await response.json()).access_token}` };
  const me = await request.get(`${api}/users/me`, { headers });
  return { email, headers, id: (await me.json()).id };
}
async function company(request: APIRequestContext, name: string, marker: number) {
  const owner = await signup(request, name, marker);
  const created = await request.post(`${api}/companies/`, { headers: owner.headers, data: { name: `${name} ${marker}`, workspace_type: "zeitarbeit" } });
  expect(created.ok(), await created.text()).toBeTruthy();
  const branding = await request.get(`${api}/companies/workspace/branding`, { headers: owner.headers });
  expect(branding.ok(), await branding.text()).toBeTruthy();
  return { ...owner, slug: (await branding.json()).slug };
}
async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("E-Mail").fill(email);
  await page.getByLabel("Passwort", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page).not.toHaveURL(/\/login$/);
}
async function accessible(page: Page) {
  const result = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(result.violations.filter(v => ["critical", "serious"].includes(v.impact ?? ""))).toEqual([]);
}
async function showResult(locator: Locator) {
  // Align the result below the sticky navigation so screenshots show the outcome.
  await locator.evaluate(element => window.scrollTo({ top: window.scrollY + element.getBoundingClientRect().top - 120, behavior: "instant" }));
}

test.beforeEach(async ({ baseURL }) => {
  if (!baseURL || !["localhost", "127.0.0.1"].includes(new URL(baseURL).hostname)) throw new Error("Only local synthetic tests");
  mkdirSync(captures, { recursive: true });
});

test("tenant branding, legacy login migration and reviewed process are usable", async ({ page, browser, request, baseURL }) => {
  test.setTimeout(180_000);
  // API setup: synthetic company, second HR administrator and a job. All product actions below use visible controls.
  const marker = Date.now();
  const owner = await company(request, "BrandOwner", marker);
  const reviewer = await signup(request, "ProcessReviewer", marker);
  const invitation = await request.post(`${api}/companies/workspace/invitations`, { headers: owner.headers, data: { email: reviewer.email, role: "admin" } });
  expect(invitation.ok(), await invitation.text()).toBeTruthy();
  const joined = await request.post(`${api}/companies/workspace/invitations/accept`, { headers: reviewer.headers, data: { token: (await invitation.json()).token } });
  expect(joined.ok(), await joined.text()).toBeTruthy();
  const job = await request.post(`${api}/jobs/recruiter`, { headers: owner.headers, data: { title: "Lagerfachkraft Test", company: "Testbetrieb", location: "Berlin" } });
  expect(job.ok(), await job.text()).toBeTruthy();
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await login(page, owner.email);
  // Simulate the old localStorage format of this same, browser-created session.
  await page.evaluate(() => {
    for (const type of ["access", "refresh"]) {
      const token = localStorage.getItem(`palmscout_${type}_token`);
      if (!token) throw new Error("Missing current session");
      localStorage.setItem(`hireos_${type}_token`, token);
      localStorage.removeItem(`palmscout_${type}_token`);
    }
  });
  await page.reload();
  await expect(page).toHaveURL(/\/dashboard/);
  await expect.poll(() => page.evaluate(() => !!localStorage.getItem("palmscout_access_token") && !localStorage.getItem("hireos_access_token"))).toBe(true);
  await page.goto("/dashboard/branding");
  await page.context().route(testLogo, route => route.fulfill({ contentType: "image/svg+xml", body: logoSvg }));
  await page.getByLabel("Anzeigename").fill("Sonnenpersonal");
  await page.getByLabel("Logo-Adresse (HTTPS)").fill(testLogo);
  await page.getByLabel("Markenfarbe").evaluate((input: HTMLInputElement) => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "#ffff00");
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await page.getByRole("button", { name: "Markenauftritt speichern" }).click();
  await expect(page.getByRole("status")).toContainText("Markenauftritt gespeichert");
  await expect(page.locator("header").first()).toContainText("Sonnenpersonal");
  await page.reload();
  await expect(page.getByLabel("Anzeigename")).toHaveValue("Sonnenpersonal");
  await expect(page.getByLabel("Markenfarbe")).toHaveValue("#ffff00");
  await accessible(page);
  await page.screenshot({ path: `${captures}/branding-desktop.png`, fullPage: false });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await expect(page.locator("header").first().getByRole("button", { name: "Abmelden" })).toBeVisible();
  await page.screenshot({ path: `${captures}/branding-mobile.png`, fullPage: false });
  await page.setViewportSize({ width: 1440, height: 1000 });
  const publicPage = await page.context().newPage();
  await publicPage.goto(`/whitelabel/${owner.slug}`);
  await expect(publicPage.locator("header")).toContainText("Sonnenpersonal");
  await expect(publicPage.locator("header")).toHaveCSS("color", "rgb(0, 0, 0)");
  await accessible(publicPage);
  await publicPage.setViewportSize({ width: 390, height: 844 });
  expect(await publicPage.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await publicPage.screenshot({ path: `${captures}/careers-mobile.png`, fullPage: true });
  await publicPage.close();
  await page.goto("/dashboard/processes");
  await page.getByLabel("Prozess aktivieren", { exact: true }).check();
  await page.getByRole("button", { name: "Prozess speichern", exact: true }).click();
  await expect(page.getByRole("status")).toHaveText("Prozess gespeichert.");
  await page.getByRole("combobox", { name: "Stelle", exact: true }).selectOption({ label: "Lagerfachkraft Test · Testbetrieb" });
  await page.getByRole("button", { name: "Prozess starten", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Stelle vorbereiten · Prüfung erforderlich" })).toBeVisible();
  await page.getByLabel("Prüfvermerk").fill("Eigene Prüfung");
  await expect(page.getByRole("button", { name: "Schritt freigeben" })).toBeDisabled();
  const reviewerContext = await browser.newContext({ baseURL });
  await reviewerContext.route(testLogo, route => route.fulfill({ contentType: "image/svg+xml", body: logoSvg }));
  const reviewPage = await reviewerContext.newPage();
  await login(reviewPage, reviewer.email);
  await reviewPage.goto("/dashboard/processes");
  await reviewPage.locator("section").filter({ has: reviewPage.getByRole("heading", { name: "Letzte Läufe" }) }).getByRole("button").first().click();
  await reviewPage.getByLabel("Prüfvermerk").fill("Stellendaten und Ansprache sachlich geprüft.");
  await reviewPage.getByRole("button", { name: "Schritt freigeben" }).click();
  await expect(reviewPage.getByRole("heading", { name: "Stelle vorbereiten · Abgeschlossen" })).toBeVisible();
  await accessible(reviewPage);
  await showResult(reviewPage.getByRole("heading", { name: "Stelle vorbereiten · Abgeschlossen" }));
  await reviewPage.screenshot({ path: `${captures}/process-reviewed-desktop.png`, fullPage: false });
  await reviewPage.setViewportSize({ width: 390, height: 844 });
  expect(await reviewPage.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await showResult(reviewPage.getByRole("heading", { name: "Stelle vorbereiten · Abgeschlossen" }));
  await reviewPage.screenshot({ path: `${captures}/process-mobile.png`, fullPage: false });
  await reviewerContext.close();
  await page.goto("/legal/impressum");
  await expect(page.getByRole("heading", { name: "palmscout – ein Produkt von neurofunken" })).toBeVisible();
  await expect(page.getByRole("note")).toContainText("Entwurf");
  await expect(page.locator('a[href="mailto:null"]')).toHaveCount(0);
  await expect(page.locator('a[href*="consumers/odr"]')).toHaveCount(0);
  await page.goto("/dashboard");
  await page.getByRole("button", { name: "Abmelden", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  expect(await page.evaluate(() => ["palmscout_access_token", "palmscout_refresh_token", "hireos_access_token", "hireos_refresh_token"].every(k => !localStorage.getItem(k)))).toBe(true);
  expect(errors).toEqual([]);
});

test("two companies collaborate and staffing travel plans persist", async ({ page, browser, request, baseURL }) => {
  test.setTimeout(180_000);
  // API setup is limited to two synthetic firms and one active worker.
  const marker = Date.now();
  const a = await company(request, "PartnerAlpha", marker);
  const b = await company(request, "PartnerBeta", marker);
  const worker = await signup(request, "PlanWorker", marker);
  const activated = await request.post(`${api}/zeitarbeit/workers/activate`, { headers: a.headers, data: { user_id: worker.id } });
  expect(activated.ok(), await activated.text()).toBeTruthy();
  await login(page, a.email);
  await page.goto("/dashboard/cooperations");
  await page.getByLabel("Arbeitsbereich-Kennung der Partnerfirma").fill(b.slug);
  await page.getByLabel("Zweck der Zusammenarbeit").fill("Gemeinsame Kapazitätsplanung für synthetische Lageraufträge");
  await page.getByRole("button", { name: "Kooperation anfragen", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Kooperation angefragt");
  const otherContext = await browser.newContext({ baseURL });
  const other = await otherContext.newPage();
  await login(other, b.email);
  await other.goto("/dashboard/cooperations");
  await other.getByRole("button", { name: "Kooperation annehmen" }).click();
  await expect(other.getByRole("heading", { name: "Personalbedarf teilen" })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: new RegExp(`PartnerBeta ${marker}.*Aktiv`) }).click();
  await page.getByLabel("Aufgabe / Berufsbild").fill("Kommissionierung Test");
  await page.getByLabel("Einsatzort", { exact: true }).fill("Berlin");
  await page.getByLabel("Einsatzbeginn").fill("2026-10-12");
  await page.getByLabel("Benötigte Personen").fill("4");
  await page.getByRole("button", { name: "Bedarf teilen", exact: true }).click();
  await expect(page.getByRole("article")).toContainText("Bedarf: 4");
  await other.reload();
  await other.getByRole("button", { name: new RegExp(`PartnerAlpha ${marker}.*Aktiv`) }).click();
  await other.getByLabel("Kapazität für Kommissionierung Test").fill("3");
  await other.getByRole("button", { name: "Kapazität anbieten" }).click();
  await expect(other.getByRole("article")).toContainText("Angebotene Kapazität: 3");
  await accessible(other);
  await showResult(other.getByRole("heading", { name: "Gemeinsame Bedarfe" }));
  await other.screenshot({ path: `${captures}/cooperation-desktop.png`, fullPage: false });
  await page.getByRole("button", { name: "Zugriff widerrufen" }).click();
  await expect(page.getByRole("status")).toContainText("widerrufen");
  await other.reload();
  await expect(other.getByRole("article")).toHaveCount(0);
  await expect(other.getByRole("button", { name: new RegExp(`PartnerAlpha ${marker}.*Widerrufen`) })).toBeVisible();
  await otherContext.close();
  await page.goto("/dashboard/mobility");
  await page.getByLabel("Planungsname").fill("Synthetische Frühschicht");
  await page.getByLabel("Schichtbeginn", { exact: true }).fill("2026-10-12T08:00");
  await page.getByLabel("Schichtende", { exact: true }).fill("2026-10-12T16:00");
  await page.getByLabel("Bedarf 1", { exact: true }).fill("Lager Berlin");
  await page.getByLabel("Personalbedarf 1", { exact: true }).fill("2");
  await page.getByLabel("Treffpunkt 1", { exact: true }).fill("Bahnhof");
  await page.getByLabel("Fahrzeug 1", { exact: true }).fill("Testbus 1");
  await page.getByLabel("Fahrzeitquelle / Stand 1", { exact: true }).fill("Manuelle Testfahrt, synthetisch");
  await page.getByLabel("Sitzplätze 1", { exact: true }).fill("1");
  await page.getByRole("checkbox", { name: "PlanWorker", exact: true }).check();
  await page.getByLabel("Treffpunkt PlanWorker", { exact: true }).fill("Bahnhof");
  await page.getByLabel("Verfügbar ab PlanWorker", { exact: true }).fill("2026-10-12T06:00");
  await page.getByLabel("Verfügbar bis PlanWorker", { exact: true }).fill("2026-10-12T19:00");
  await page.getByRole("button", { name: "Planungsvorschlag berechnen" }).click();
  await expect(page.getByRole("heading", { name: "Planungsvorschlag: Synthetische Frühschicht" })).toBeVisible();
  await expect(page.getByText("1 von 2 besetzt", { exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "Testbus 1 · Bahnhof" })).toBeVisible();
  await accessible(page);
  await showResult(page.getByRole("heading", { name: "Planungsvorschlag: Synthetische Frühschicht" }));
  await page.screenshot({ path: `${captures}/mobility-desktop.png`, fullPage: false });
  await page.reload();
  await page.getByRole("button", { name: /Synthetische Frühschicht/ }).click();
  await expect(page.getByText("1 von 2 besetzt", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await showResult(page.getByRole("heading", { name: "Planungsvorschlag: Synthetische Frühschicht" }));
  await page.screenshot({ path: `${captures}/mobility-mobile.png`, fullPage: false });
  await showResult(page.getByRole("article"));
  await expect(page.getByRole("article")).toContainText("Testbus 1 · Bahnhof");
  await expect(page.getByRole("article")).toContainText("Abfahrt");
  await expect(page.getByRole("article")).toContainText("Rückkehr");
  await accessible(page);
  await page.screenshot({ path: `${captures}/mobility-allocation-mobile.png`, fullPage: false });
  // Synthetic branding setup exercises the separate employee portal with a wide logo.
  const settings = await request.get(`${api}/companies/workspace/branding`, { headers: a.headers });
  expect(settings.ok(), await settings.text()).toBeTruthy();
  const branded = await request.put(`${api}/companies/workspace/branding`, { headers: a.headers, data: {
    version: (await settings.json()).version, brand_name: "Personalplanung mit langem Firmennamen", primary_color: "#ffff00", logo_url: testLogo,
  } });
  expect(branded.ok(), await branded.text()).toBeTruthy();
  const workerContext = await browser.newContext({ baseURL, viewport: { width: 390, height: 844 } });
  await workerContext.route(testLogo, route => route.fulfill({ contentType: "image/svg+xml", body: logoSvg }));
  const workerPage = await workerContext.newPage();
  await login(workerPage, worker.email);
  await expect(workerPage).toHaveURL(/\/worker/);
  await expect(workerPage.locator("header")).toContainText("Personalplanung mit langem Firmennamen");
  expect(await workerPage.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await expect(workerPage.getByRole("button", { name: "Abmelden", exact: true })).toBeVisible();
  await workerPage.screenshot({ path: `${captures}/worker-branding-mobile.png`, fullPage: false });
  await workerContext.close();
});
