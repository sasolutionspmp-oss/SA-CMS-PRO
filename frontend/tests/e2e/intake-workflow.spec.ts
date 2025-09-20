import { test, expect } from "@playwright/test";

test("intake launch calls API", async ({ page }) => {
  const mockRun = {
    run_id: "run-123",
    project_id: "ACME-001",
    status: "ready",
    total: 1,
    pending: 0,
    parsed: 1,
    failed: 0,
    started_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    completed_at: new Date().toISOString(),
    items: [],
  };

  let launchCalled = false;
  await page.route("**/api/intake/launch", async (route) => {
    launchCalled = true;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mockRun),
    });
  });
  await page.route("**/api/intake/status**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(mockRun),
    });
  });

  await page.goto("/");

  await page.getByLabel("Project ID").fill("ACME-001");
  await page.getByLabel("ZIP path").fill("C:/Uploads/acme.zip");

  await Promise.all([
    page.waitForResponse((response) =>
      response.url().includes("/api/intake/launch") && response.status() === 200
    ),
    page.getByRole("button", { name: "Launch Intake" }).click(),
  ]);

  await expect.poll(() => launchCalled).toBeTruthy();
});
