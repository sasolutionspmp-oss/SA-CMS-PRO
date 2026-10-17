import { expect, type Locator } from '@playwright/test';

// UI5 renders its accessible checked state after the click event. Keep one
// user interaction and await the rendered state before any reviewed action.
export async function checkUi5Checkbox(checkbox: Locator): Promise<void> {
  await expect(checkbox).not.toBeChecked();
  await checkbox.click();
  await expect(checkbox).toBeChecked();
}
