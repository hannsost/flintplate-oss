import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// Writes create only synthetic accounts and jobs, and are restricted to localhost.
test.beforeEach(async ({ baseURL }) => {
  if (!baseURL || !["localhost", "127.0.0.1"].includes(new URL(baseURL).hostname))
    throw new Error("This synthetic workflow suite may only run against localhost.");
});

for (const [type] of [
  ["internal_hr", "HR-Arbeitsbereich"],
  ["recruiter_agency", "Recruiting & Vermittlung"],
  ["zeitarbeit", "Disposition & Recruiting"],
] as const) {
  test(`${type}: register workspace, create and edit a job`, async ({ page }) => {
    test.setTimeout(120_000);
    const marker = `E2E-${type}-${Date.now()}`;
    const errors: string[] = [];
    page.on("pageerror", e => errors.push(e.message));
    page.on("response", r => { if (r.url().startsWith("http://localhost:8001/") && r.status() >= 400) errors.push(`${r.status()} ${new URL(r.url()).pathname}`); });
    await page.goto("/register/recruiter");
    await page.getByLabel("Name", { exact: true }).fill("Test Team");
    await page.getByLabel("E-Mail", { exact: true }).fill(`${marker.toLowerCase()}@example.com`);
    await page.getByLabel("Passwort", { exact: true }).fill("SyntheticOnly123!");
    await page.getByRole("checkbox").check();
    await page.getByRole("button", { name: "Weiter" }).click();
    await page.getByLabel("Wie arbeitet dein Team?").selectOption(type);
    await page.getByLabel("Unternehmensname", { exact: false }).fill(marker);
    await page.getByRole("checkbox").check();
    await page.locator('form button[type="submit"]').click();
    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByRole("heading", { name: "Heute", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Raum für deinen nächsten Schritt" })).toBeVisible();
    if (type === "internal_hr") {
      await expect(page.getByText("Provision (Monat)", { exact: true })).toHaveCount(0);
      await page.screenshot({ path: "../.artifacts/browser/hr-workspace.png", fullPage: true });
    }
    await page.getByRole("link", { name: "+ Neues Inserat", exact: true }).click();
    await page.getByLabel("Stellenbezeichnung").fill(`${marker} Entwickler`);
    await page.getByLabel("Unternehmen", { exact: false }).fill(marker);
    await page.getByLabel("Standort", { exact: true }).fill("Berlin");
    await page.getByLabel("Gewünschte Skills").fill("Python, python, SQL");
    await page.getByLabel("Stellenbeschreibung", { exact: true }).fill("Synthetisches Testinserat für die lokale Qualitätssicherung.");
    await page.locator('form button[type="submit"]').click();
    await expect(page).toHaveURL(/\/dashboard\/jobs$/);
    await page.goto("/dashboard/jobs");
    const job = page.locator('[data-slot="card"]').filter({ has: page.getByRole("heading", { name: `${marker} Entwickler`, exact: true }) });
    await expect(job).toBeVisible();
    await job.getByRole("link", { name: "Bearbeiten", exact: true }).click();
    await page.getByLabel("Stellenbezeichnung").fill(`${marker} Senior Entwickler`);
    await page.locator('form button[type="submit"]').click();
    await expect(page).toHaveURL(/\/dashboard\/jobs$/);
    const editedJob = page.locator('[data-slot="card"]').filter({ has: page.getByRole("heading", { name: `${marker} Senior Entwickler`, exact: true }) });
    await expect(editedJob).toBeVisible();
    await editedJob.getByRole("button", { name: "Archivieren", exact: true }).click();
    await editedJob.getByRole("button", { name: "Archivierung bestätigen", exact: true }).click();
    await expect(editedJob.getByText("Archiviert", { exact: true })).toBeVisible();
    if (type === "zeitarbeit") {
      await page.goto("/dashboard/zeitarbeit");
      await page.getByRole("button", { name: "+ Neuer Auftrag" }).click();
      await page.getByLabel("Titel *", { exact: true }).fill(`${marker} Lagerauftrag`);
      await page.getByLabel("Einsatzort", { exact: true }).fill("Berlin");
      await page.getByLabel("Benötigte Skills (kommagetrennt)").fill("Stapler, Lagerlogistik");
      await page.getByRole("button", { name: "Anlegen", exact: true }).click();
      await expect(page.getByText(`${marker} Lagerauftrag`, { exact: true })).toBeVisible();
      await page.reload();
      await page.getByText(`${marker} Lagerauftrag`, { exact: true }).click();
      await page.getByRole("button", { name: "Bearbeiten", exact: true }).click();
      await page.getByLabel("Titel *", { exact: true }).fill(`${marker} Neuer Lagerauftrag`);
      await page.getByRole("button", { name: "Speichern", exact: true }).click();
      await expect(page.getByText(`${marker} Neuer Lagerauftrag`, { exact: true }).first()).toBeVisible();
      page.once("dialog", d => d.accept());
      await page.getByRole("button", { name: "Auftrag löschen", exact: true }).click();
      await expect(page.getByText(`${marker} Neuer Lagerauftrag`, { exact: true })).toHaveCount(0);
    }
    expect(errors).toEqual([]);
  });
}

test("worker pages and previous-month navigation load real data", async ({ page }) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("response", r => { if (r.url().startsWith("http://localhost:8001/") && r.status() >= 400) errors.push(`${r.status()} ${new URL(r.url()).pathname}`); });
  await page.goto("/login");
  await page.getByLabel("E-Mail").fill("kalle.brenner@quickwork.de");
  await page.getByLabel("Passwort", { exact: true }).fill("Worker2025!");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page).toHaveURL(/\/worker$/);
  for (const route of ["/worker", "/worker/time", "/worker/schedule", "/worker/documents", "/worker/profile", "/worker/absences", "/worker/equipment", "/worker/tasks", "/worker/payroll", "/worker/interviews", "/worker/tickets"]) {
    await page.goto(route);
    await expect(page.locator("h1").first()).toBeVisible();
    await expect(page.locator(".animate-spin")).toHaveCount(0);
    await page.waitForTimeout(300);
  }
  await page.goto("/worker/time");
  const response = page.waitForResponse(r => r.url().includes("/worker/time") && r.request().method() === "GET" && r.url().includes("month="));
  await page.getByRole("button", { name: "Vorheriger Monat" }).click();
  expect((await response).ok()).toBeTruthy();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({ path: "../.artifacts/browser/worker-time.png", fullPage: true });
  expect(errors).toEqual([]);
});

test("login is accessible by label and has no serious WCAG violations", async ({ page }) => {
  await page.goto("/login");
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(results.violations.filter(v => ["serious", "critical"].includes(v.impact ?? ""))).toEqual([]);
});
