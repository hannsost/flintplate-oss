import { test, expect, type APIRequestContext, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { mkdirSync, readFileSync } from "node:fs";
import { createHash } from "node:crypto";

const api = "http://localhost:8001";
const password = "SyntheticOnly123!";
const captures = "/tmp/hireos-browser-tests/palmscout-finance";

async function account(request: APIRequestContext, marker: number, name: string) {
  const email = `${name.toLowerCase().replaceAll(" ", "-")}-${marker}@example.com`;
  const result = await request.post(`${api}/auth/register`, { data: { email, password, full_name: name } });
  expect(result.ok(), await result.text()).toBeTruthy();
  return { email, headers: { Authorization: `Bearer ${(await result.json()).access_token}` } };
}
async function login(page: Page, email: string) {
  await page.goto("/login");
  await page.getByLabel("E-Mail", { exact: true }).fill(email);
  await page.getByLabel("Passwort", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard/);
  await page.goto("/dashboard/finance");
}
async function accessible(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(results.violations.filter(v => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
}
async function showInvoice(page: Page) {
  await page.locator("#invoice-detail").evaluate(el => window.scrollTo({ top: window.scrollY + el.getBoundingClientRect().top - 120, behavior: "instant" }));
}

test("finance permissions, four-eyes invoice, real XRechnung and full cancellation", async ({ page, request, browser, baseURL }) => {
  test.setTimeout(180_000);
  if (!baseURL || !["localhost", "127.0.0.1"].includes(new URL(baseURL).hostname)) throw new Error("Local synthetic data only");
  mkdirSync(captures, { recursive: true });
  // API setup is limited to synthetic accounts and workspace membership.
  const marker = Date.now();
  const owner = await account(request, marker, "Finance Owner");
  const reviewer = await account(request, marker, "Finance Reviewer");
  const company = await request.post(`${api}/companies/`, { headers: owner.headers, data: { name: `Finanztest ${marker}`, workspace_type: "zeitarbeit" } });
  expect(company.ok(), await company.text()).toBeTruthy();
  const invitation = await request.post(`${api}/companies/workspace/invitations`, { headers: owner.headers, data: { email: reviewer.email, role: "recruiter" } });
  expect(invitation.ok(), await invitation.text()).toBeTruthy();
  const joined = await request.post(`${api}/companies/workspace/invitations/accept`, { headers: reviewer.headers, data: { token: (await invitation.json()).token } });
  expect(joined.ok(), await joined.text()).toBeTruthy();
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await login(page, owner.email);
  await page.getByRole("button", { name: "Ersten Aussteller anlegen" }).click();
  for (const [label, value] of [
    ["Aussteller Name / Firma", "Pilot Personal GmbH"], ["Aussteller Straße und Hausnummer", "Teststraße 1"],
    ["Aussteller Postleitzahl", "10115"], ["Aussteller Ort", "Berlin"], ["Aussteller E-Mail", "finance@example.com"],
    ["Umsatzsteuer-ID", "DE123456789"], ["Ansprechpartner", "Testkontakt Finanzen"], ["Telefon", "+49 30 123456"],
    ["Deutsche IBAN", "DE89370400440532013000"], ["Rechnungspräfix", "TEST"],
  ]) await page.getByLabel(label, { exact: true }).fill(value);
  await page.getByRole("button", { name: "Aussteller anlegen", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Rechnungsaussteller gespeichert");
  await page.getByRole("button", { name: "Finanzrechte", exact: true }).click();
  await page.getByRole("checkbox", { name: "Prüfen für Finance Reviewer", exact: true }).check();
  await page.getByRole("checkbox", { name: "Exportieren für Finance Reviewer", exact: true }).check();
  await page.getByRole("button", { name: "Rechte für Finance Reviewer speichern" }).click();
  await expect(page.getByRole("status")).toContainText("Finanzrechte für Finance Reviewer gespeichert");
  await page.getByRole("button", { name: "Rechnungen", exact: true }).click();
  await page.getByRole("button", { name: "Neue Rechnung", exact: true }).click();
  for (const [label, value] of [
    ["Empfänger Name / Firma", "Pilotkunde GmbH"], ["Empfänger Straße und Hausnummer", "Testweg 2"],
    ["Empfänger Postleitzahl", "10117"], ["Empfänger Ort", "Berlin"], ["Empfänger E-Mail", "buyer@example.com"],
    ["Käuferreferenz", "REFERENZ-2026"], ["Eindeutige Leistungsreferenz", "TESTAUFTRAG-SEPTEMBER"],
    ["Rechnungsdatum", "2026-09-10"], ["Fällig am", "2026-09-24"], ["Leistungsbeginn", "2026-09-01"], ["Leistungsende", "2026-09-10"],
    ["Leistung 1", "Personalservice Test"], ["Menge 1", "8.5"], ["Nettopreis 1", "32.75"],
  ]) await page.getByLabel(label, { exact: true }).fill(value);
  await page.getByRole("button", { name: "Entwurf speichern", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Rechnung ohne Nummer", exact: true })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Beträge wurden berechnet");
  await page.getByRole("button", { name: "Entwurf bearbeiten", exact: true }).click();
  await page.getByLabel("Käuferreferenz", { exact: true }).fill("GEPRUEFT-2026");
  await page.getByRole("button", { name: "Entwurf speichern", exact: true }).click();
  await expect(page.getByText("GEPRUEFT-2026", { exact: true })).toBeVisible();
  await page.getByLabel("Prüfvermerk", { exact: true }).fill("Leistung und Stundensatz abgeglichen.");
  await page.getByRole("button", { name: "Zur Prüfung vorlegen" }).click();
  await expect(page.getByRole("button", { name: "Fachlich freigeben" })).toBeDisabled();
  const context = await browser.newContext({ baseURL });
  const reviewPage = await context.newPage();
  reviewPage.on("pageerror", e => errors.push(e.message));
  await login(reviewPage, reviewer.email);
  await expect(reviewPage.getByRole("button", { name: "Neue Rechnung", exact: true })).toHaveCount(0);
  await reviewPage.getByRole("button", { name: /Entwurf · Pilotkunde GmbH/ }).click();
  await reviewPage.getByLabel("Prüfvermerk", { exact: true }).fill("Empfänger, Leistungsnachweis, Steuer und Zahlungsdaten geprüft.");
  await reviewPage.getByRole("button", { name: "Fachlich freigeben" }).click();
  await expect(reviewPage.getByRole("status")).toContainText("Freigegeben");
  await page.getByRole("button", { name: "Finanzbereich aktualisieren" }).click();
  await page.getByLabel("Prüfvermerk", { exact: true }).fill("Geprüften Rechnungsstand finalisieren.");
  await page.getByRole("button", { name: "Prüfen & finalisieren" }).click();
  await expect(page.getByRole("heading", { name: "Rechnung TEST-2026-000001", exact: true })).toBeVisible({ timeout: 40_000 });
  await expect(page.getByText("XRechnungsprüfung bestanden", { exact: true })).toBeVisible();
  await accessible(page);
  const [download] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "XRechnung herunterladen" }).click()]);
  expect(download.suggestedFilename()).toBe("TEST-2026-000001.xml");
  await download.saveAs(`${captures}/synthetic-invoice.xml`);
  const xml = readFileSync(`${captures}/synthetic-invoice.xml`);
  expect(xml.toString()).toContain("urn:xeinkauf.de:kosit:xrechnung_3.0");
  expect(xml.toString()).toContain('currencyID="EUR">331.27');
  const issuers = await request.get(`${api}/finance/entities`, { headers: owner.headers });
  const list = await request.get(`${api}/finance/invoices?entity_id=${(await issuers.json())[0].id}`, { headers: owner.headers });
  expect((await list.json())[0].artifact_hash).toBe(createHash("sha256").update(xml).digest("hex"));
  const [report] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Prüfbericht herunterladen" }).click()]);
  await report.saveAs(`${captures}/synthetic-report.xml`);
  expect(readFileSync(`${captures}/synthetic-report.xml`, "utf8")).toContain("KoSIT Validator 1.6.3");
  await showInvoice(page);
  await page.screenshot({ path: `${captures}/invoice-desktop.png`, fullPage: false });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await showInvoice(page);
  await accessible(page);
  await page.screenshot({ path: `${captures}/invoice-mobile.png`, fullPage: false });
  await page.getByText("Rechnung vollständig stornieren", { exact: true }).click();
  await page.getByLabel("Stornodatum", { exact: true }).fill("2026-09-11");
  await page.getByLabel("Stornogrund", { exact: true }).fill("Synthetischer Auftrag vollständig aufgehoben.");
  await page.getByRole("button", { name: "Stornobeleg vorbereiten" }).click();
  await expect(page.getByRole("heading", { name: "Stornobeleg ohne Nummer", exact: true })).toBeVisible();
  await page.getByLabel("Prüfvermerk", { exact: true }).fill("Vollständigen Stornobeleg prüfen lassen.");
  await page.getByRole("button", { name: "Zur Prüfung vorlegen" }).click();
  await reviewPage.reload();
  await reviewPage.getByRole("button", { name: /Entwurf · Pilotkunde GmbH.*Stornobeleg/ }).click();
  await reviewPage.getByLabel("Prüfvermerk", { exact: true }).fill("Stornogrund und Bezug zur Originalrechnung geprüft.");
  await reviewPage.getByRole("button", { name: "Fachlich freigeben" }).click();
  await expect(reviewPage.getByRole("status")).toContainText("Freigegeben");
  await page.getByRole("button", { name: "Finanzbereich aktualisieren" }).click();
  await page.getByLabel("Prüfvermerk", { exact: true }).fill("Stornobeleg finalisieren.");
  await page.getByRole("button", { name: "Prüfen & finalisieren" }).click();
  await expect(page.getByRole("heading", { name: "Stornobeleg TEST-2026-000002", exact: true })).toBeVisible({ timeout: 40_000 });
  await page.getByRole("button", { name: /TEST-2026-000001 · Pilotkunde GmbH/ }).click();
  await expect(page.getByText(/^Storniert · Version/)).toBeVisible();
  await showInvoice(page);
  await page.screenshot({ path: `${captures}/cancelled-mobile.png`, fullPage: false });
  await page.getByRole("button", { name: "Finanzrechte", exact: true }).click();
  for (const label of ["Lesen", "Prüfen", "Exportieren"]) await page.getByRole("checkbox", { name: `${label} für Finance Reviewer`, exact: true }).uncheck();
  await page.getByRole("button", { name: "Rechte für Finance Reviewer speichern" }).click();
  await expect(page.getByRole("status")).toContainText("Finanzrechte für Finance Reviewer gespeichert");
  await reviewPage.reload();
  await expect(reviewPage.getByText(/Für Ihr Konto wurde noch kein Rechnungsaussteller freigegeben/)).toBeVisible();
  await expect(reviewPage.getByRole("button", { name: /Pilotkunde GmbH/ })).toHaveCount(0);
  await context.close();
  expect(errors).toEqual([]);
});
