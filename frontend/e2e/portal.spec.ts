import { test, expect, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";

// Synthetic local seed accounts documented in TEST_USERS.md. Never target a
// customer environment with these credentials or this write-capable test suite.
const accounts = {
  recruiter: ["recruiter@demo-enterprise.de", "Recruiter1234!"],
  admin: ["admin@hireos.test", "Admin1234!"],
  candidate: ["kandidat@hireos.test", "Kandidat1234!"],
  companyAdmin: ["admin-recruiter@demo-enterprise.de", "AdminRec1234!"],
} as const;

async function login(page: Page, role: keyof typeof accounts) {
  await page.goto("/login");
  await page.getByLabel("E-Mail").fill(accounts[role][0]);
  await page.getByLabel("Passwort", { exact: true }).fill(accounts[role][1]);
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

test("login rejects invalid credentials visibly", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("E-Mail").fill("nonexistent@palmscout.test");
  await page.getByLabel("Passwort", { exact: true }).fill("WrongPassword123!");
  await page.getByRole("button", { name: "Anmelden", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "E-Mail oder Passwort falsch." })).toBeVisible();
});

const routes = {
  recruiter: ["/dashboard", "/dashboard/interviews", "/dashboard/candidates", "/dashboard/pipeline", "/dashboard/kanban", "/dashboard/documents", "/dashboard/org-charts", "/dashboard/zeitarbeit", "/dashboard/zeitarbeit/workers", "/dashboard/zeitarbeit/time-approval", "/dashboard/zeitarbeit/assignments", "/dashboard/settings"],
  admin: ["/admin", "/admin/customers/new", "/admin/import-runs", "/admin/teams"],
  candidate: ["/profile", "/jobs", "/applications", "/settings"],
} as const;

for (const role of Object.keys(routes) as Array<keyof typeof routes>) {
  test(`${role}: pages load without JavaScript or API failures`, async ({ page }) => {
    test.setTimeout(120_000);
    const errors: string[] = [];
    page.on("pageerror", error => errors.push(error.message));
    page.on("response", response => {
      if (response.url().startsWith("http://localhost:8001/") && response.status() >= 400)
        errors.push(`${response.status()} ${new URL(response.url()).pathname}`);
    });
    await login(page, role);
    for (const route of routes[role]) {
      await page.goto(route);
      await expect(page).not.toHaveURL(/\/login/);
      await expect(page.locator("h1").first()).toBeVisible();
      await expect(page.locator(".animate-spin")).toHaveCount(0);
      if (role === "candidate" && route === "/jobs") {
        await expect(page.getByRole("button", { name: /Testjobs laden/ })).toHaveCount(0);
        const captures = "/tmp/hireos-browser-tests/palmscout-publication";
        mkdirSync(captures, { recursive: true });
        await page.screenshot({ path: `${captures}/candidate-feed-desktop.png` });
      }
      await page.waitForTimeout(300);
      await expect(page.getByText("[object Object]", { exact: true })).toHaveCount(0);
    }
    expect(errors).toEqual([]);
  });
}

test("recruiter gets a clear restriction on plan management", async ({ page }) => {
  await login(page, "recruiter");
  await page.goto("/dashboard/plan");
  await expect(page.getByRole("alert").filter({ hasText: "Nur Administratoren" })).toBeVisible();
  await expect(page.getByText("Kein Tenant zugewiesen")).toHaveCount(0);
});

test("mobile navigation preserves content width and closes after navigation", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, "recruiter");
  await page.goto("/dashboard");
  const menu = page.getByRole("button", { name: "Menü öffnen" });
  await expect(menu).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await menu.click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("dialog").getByRole("link", { name: "Bewerbungen", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard\/applications/);
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(page.locator(".animate-spin")).toHaveCount(0);
  await page.screenshot({ path: "../.artifacts/browser/mobile-applications.png", fullPage: true });
  await menu.click();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).not.toBeVisible();
  await expect(menu).toBeFocused();
});


test("company admin stays in their company portal", async ({ page }) => {
  await login(page, "companyAdmin");
  await expect(page.locator("h1").first()).toBeVisible();
  await expect(page.locator(".animate-spin")).toHaveCount(0);
  await expect(page).toHaveURL(/\/dashboard$/);
  await page.goto("/admin/customers/new");
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await page.goto("/dashboard/teams");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expect(page.locator(".animate-spin")).toHaveCount(0);
  await page.screenshot({ path: "../.artifacts/browser/company-admin-teams.png", fullPage: true });
});

test("candidate explicitly shares and revokes their profile", async ({ page, context }) => {
  await login(page, "candidate");
  await page.goto("/profile");
  const publish = page.getByRole("button", { name: "Profil öffentlich teilen" });
  await expect(publish).toBeDisabled();
  await page.getByRole("checkbox", { name: /Ich möchte mein Profil inklusive Kontaktangaben/ }).check();
  await publish.click();
  const link = page.getByRole("link").filter({ hasText: /http.*\/profile\// });
  await expect(link).toBeVisible();
  const url = await link.getAttribute("href");
  expect(url).toBeTruthy();
  const publicPage = await context.newPage();
  const loadedProfile = publicPage.waitForResponse(r => /\/profiles\/[0-9a-f-]+$/.test(new URL(r.url()).pathname));
  await publicPage.goto(url!);
  expect((await loadedProfile).status()).toBe(200);
  await expect(publicPage.getByText("Profil nicht gefunden.", { exact: true })).toHaveCount(0);
  await expect(publicPage.locator(".animate-spin")).toHaveCount(0);
  await page.getByRole("button", { name: "Profil-Link deaktivieren" }).click();
  await expect(page.getByRole("status")).toHaveText("Öffentlicher Profil-Link deaktiviert.");
  await page.getByRole("button", { name: "Profil-Link deaktivieren" }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: "../.artifacts/browser/profile-sharing-revoked.png", fullPage: true });
  await publicPage.reload();
  await expect(publicPage.getByText("Profil nicht gefunden.", { exact: true })).toBeVisible();
  await publicPage.close();
});
