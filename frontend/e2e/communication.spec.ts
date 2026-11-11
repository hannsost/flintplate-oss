import { publishFixtureJob } from "./publication-helpers";
import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

async function setup(request: APIRequestContext) {
  // API setup only: synthetic candidate, role and application in the local demo tenant.
  const marker = Date.now();
  const login = await request.post("http://localhost:8001/auth/login", { form: { username: "recruiter@demo-enterprise.de", password: "Recruiter1234!" } });
  expect(login.ok()).toBeTruthy();
  const headers = { Authorization: `Bearer ${(await login.json()).access_token}` };
  const email = `communication-${marker}@example.com`;
  const registration = await request.post("http://localhost:8001/auth/register", { data: { email, full_name: `Communication ${marker}`, password: "SyntheticOnly123!" } });
  expect(registration.ok()).toBeTruthy();
  const candidateHeaders = { Authorization: `Bearer ${(await registration.json()).access_token}` };
  const person = await request.get("http://localhost:8001/users/me", { headers: candidateHeaders });
  expect(person.ok(), await person.text()).toBeTruthy();
  const personId = (await person.json()).id;
  const job = await request.post("http://localhost:8001/jobs/recruiter", { headers, data: { employment_type: "full-time", title: `Interview ${marker}`, company: "Synthetic Communication", description: "Lokaler Kommunikationstest", location: "Berlin" } });
  expect(job.ok(), await job.text()).toBeTruthy();
  await publishFixtureJob(request, headers, await job.json());
  const app = await request.post("http://localhost:8001/applications", { headers: candidateHeaders, data: { job_id: (await job.json()).id, company: "Synthetic Communication", position: `Interview ${marker}`, status: "applied" } });
  expect(app.ok(), await app.text()).toBeTruthy();
  return { marker, email, personId, applicationId: (await app.json()).id };
}
async function login(page: Page) {
  await page.goto("/login");
  await page.getByLabel("E-Mail").fill("recruiter@demo-enterprise.de");
  await page.getByLabel("Passwort", { exact: true }).fill("Recruiter1234!");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Heute", exact: true })).toBeVisible();
}
test.beforeEach(({ baseURL }) => {
  if (!baseURL || !["localhost", "127.0.0.1"].includes(new URL(baseURL).hostname)) throw new Error("Local synthetic tests only");
});

test("person context, persisted email draft, export and explicit send review", async ({ page, request }) => {
  test.setTimeout(120_000);
  const data = await setup(request);
  const errors: string[] = [];
  page.on("pageerror", error => errors.push(error.message));
  await login(page);
  await page.goto(`/dashboard/people?person=${data.personId}`);
  await page.getByRole("link", { name: "Nachricht vorbereiten" }).click();
  await expect(page.getByRole("combobox", { name: "Empfänger", exact: true })).toHaveValue(data.personId);
  await page.getByLabel("Betreff", { exact: true }).fill("Einladung zum Kennenlernen");
  await page.getByRole("textbox", { name: "Nachricht", exact: true }).fill("Hallo, gerne möchten wir dich kennenlernen.");
  await page.getByRole("button", { name: "Entwurf speichern", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Einladung zum Kennenlernen" })).toBeVisible();
  await page.reload();
  await page.getByRole("button", { name: "Bearbeiten", exact: true }).click();
  await page.getByRole("textbox", { name: "Nachricht", exact: true }).fill("Hallo, bitte wähle einen passenden Termin aus.");
  await page.getByRole("button", { name: "Entwurf speichern", exact: true }).click();
  await expect(page.getByRole("article")).toContainText("bitte wähle einen passenden Termin");
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "EML herunterladen" }).click();
  expect((await downloadEvent).suggestedFilename()).toBe("palmscout-entwurf.eml");
  await page.getByRole("button", { name: "Versand prüfen" }).click();
  const review = page.getByRole("region", { name: "Versandfreigabe" });
  await expect(review).toBeVisible();
  await expect(review).toContainText(data.email);
  await expect(review.getByRole("button", { name: "Jetzt senden" })).toBeDisabled();
  await page.screenshot({ path: "../.artifacts/browser/communication-review.png", fullPage: true });
  const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(axe.violations.filter(v => ["critical", "serious"].includes(v.impact ?? ""))).toEqual([]);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: "../.artifacts/browser/communication-mobile.png", fullPage: true });
  await page.goto("/dashboard/connections");
  await expect(page.locator("section").filter({ has: page.getByRole("heading", { name: "Google Workspace" }) }).getByRole("button", { name: "Konto verbinden" })).toBeDisabled();
  await expect(page.locator("section").filter({ has: page.getByRole("heading", { name: "Microsoft 365" }) }).getByRole("button", { name: "Konto verbinden" })).toBeDisabled();
  expect(errors).toEqual([]);
});

test("recruiter proposes times, candidate books and status survives reload", async ({ page, browser, request }) => {
  test.setTimeout(120_000);
  const data = await setup(request);
  await login(page);
  await page.goto(`/dashboard/scheduling?application=${data.applicationId}`);
  const slot = new Date(Date.now() + 3 * 86400_000 + (data.marker % 3600) * 60_000);
  const local = `${slot.getFullYear()}-${String(slot.getMonth() + 1).padStart(2, "0")}-${String(slot.getDate()).padStart(2, "0")}T${String(slot.getHours()).padStart(2, "0")}:${String(slot.getMinutes()).padStart(2, "0")}`;
  await page.getByLabel("Terminoption 1").fill(local);
  await page.getByLabel("Gesprächsdauer").selectOption("45");
  await page.getByRole("button", { name: "Buchungslink erstellen" }).click();
  const link = page.getByLabel("Buchungslink", { exact: true });
  await expect(link).toBeVisible();
  const url = await link.inputValue();
  const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const candidate = await context.newPage();
  await candidate.goto(url);
  await candidate.getByLabel("E-Mail-Adresse").fill(data.email);
  await candidate.getByLabel("Passwort", { exact: true }).fill("SyntheticOnly123!");
  await candidate.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(candidate.getByText("Dauer: 45 Minuten.", { exact: false })).toBeVisible();
  await candidate.getByRole("radio").check();
  await candidate.screenshot({ path: "../.artifacts/browser/booking-candidate-mobile.png", fullPage: true });
  await candidate.getByRole("button", { name: "Termin verbindlich buchen" }).click();
  await expect(candidate.getByRole("heading", { name: "Dein Termin ist bestätigt" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Termin wurde gebucht" })).toBeVisible();
  await context.close();
});

test("private inbox preview prepares a draft without importing or sending mail", async ({ page, request }) => {
  const data = await setup(request);
  await login(page);
  // Provider credentials are absent locally. Only provider UI responses are synthetic;
  // authorization, filtering and OAuth persistence have separate real-database tests.
  await page.route("**/companies/workspace/connections", route => route.fulfill({ json: [{ provider: "google", configured: true, connected: true, email: "synthetic-mailbox@example.com", detail: null }, { provider: "microsoft", configured: false, connected: false, email: null, detail: null }] }));
  let reads = 0;
  await page.route("**/companies/workspace/messages/inbox?**", route => {
    reads++;
    expect(new URL(route.request().url()).searchParams.get("person_id")).toBe(data.personId);
    return route.fulfill({ json: { provider: "google", days: 90, limited: false, messages: [{ id: "synthetic-message", sender: data.email, subject: "Rückfrage zum Kennenlernen", preview: "Passt Dienstag für unser Gespräch?", received_at: new Date().toISOString() }] } });
  });
  await page.goto(`/dashboard/communication?person=${data.personId}`);
  const inbox = page.getByRole("region", { name: "Privater Posteingang zur Person" });
  await inbox.getByRole("button", { name: "Google-Posteingang laden" }).click();
  await expect(inbox).toContainText("Passt Dienstag für unser Gespräch?");
  await inbox.getByRole("button", { name: "Antwort vorbereiten" }).click();
  await expect(page.getByRole("textbox", { name: "Betreff", exact: true })).toHaveValue("Re: Rückfrage zum Kennenlernen");
  await expect(page.getByRole("textbox", { name: "Nachricht", exact: true })).toHaveValue("");
  await page.reload();
  await expect(page.getByRole("heading", { name: "Rückfrage zum Kennenlernen", exact: true })).toHaveCount(0);
  expect(reads).toBe(1);
});
