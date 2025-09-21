import { expect, test } from "@playwright/test";

test.describe("Tailwind probe standalone", () => {
  test("renders compiled tailwind utilities", async ({ page }) => {
    await page.goto("/tailwind-probe.html");
    await page.waitForLoadState("networkidle");

    const probe = page.getByTestId("tailwind-probe");
    await expect(probe).toBeVisible({ timeout: 15000 });
    await expect(probe).toContainText("@tailwindcss/postcss");

    const chips = probe.locator('[data-testid^="tailwind-probe-chip-"]');
    await expect(chips).toHaveCount(3);

    const buildChip = page.getByTestId("tailwind-probe-chip-build-status");
    const chipShadow = await buildChip.evaluate((element) => getComputedStyle(element).boxShadow);
    expect(chipShadow).not.toBe("none");

    const gradientCard = page.getByTestId("tailwind-probe-gradient-card");
    const gradientImage = await gradientCard.evaluate((element) => getComputedStyle(element).backgroundImage);
    expect(gradientImage).toContain("linear-gradient");

    const layoutGrid = page.getByTestId("tailwind-probe-layout-grid");
    const display = await layoutGrid.evaluate((element) => getComputedStyle(element).display);
    expect(display).toBe("grid");
    await expect(layoutGrid.locator("span")).toHaveCount(3);
  });
});
