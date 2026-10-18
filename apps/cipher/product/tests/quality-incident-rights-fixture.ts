import { expect, type Page } from '@playwright/test';
import { checkUi5Checkbox } from './ui5-controls';
import { document } from './quality-safety-fixture';

export async function incidentFields(page: Page) {
  for (const [label, value] of Object.entries({ 'Record title': 'Restricted fixture incident', 'Record date': '2026-10-18', 'Work location': 'Fixture location', Description: 'Fixture observation only', 'Closure item 1': 'Retain exact closure evidence', 'People, one per line': 'Fixture person', 'Restricted account': 'Private synthetic account', 'Immediate response': 'Fixture response' })) await page.getByRole('textbox', { name: label, exact: true }).fill(value);
}
export async function uploadPrivate(page: Page) {
  await page.getByLabel('Private evidence file', { exact: true }).setInputFiles({ name: 'private-observation.txt', mimeType: 'text/plain', buffer: Buffer.from('Private fixture evidence bytes') });
  for (const [label, value] of Object.entries({ 'Private evidence title': 'Private original', 'Private evidence rights basis': 'Explicit fixture upload permission', 'Private evidence locator': 'Private source paragraph 1' })) await page.getByRole('textbox', { name: label, exact: true }).fill(value);
  await page.getByRole('combobox', { name: 'Upload permission evidence', exact: true }).click();
  await page.getByRole('option', { name: `${document.title} · Rev. 1`, exact: true }).click();
  await page.getByRole('textbox', { name: 'Upload permission evidence locator', exact: true }).fill('Exact permission evidence');
  await page.getByRole('button', { name: 'Attach upload permission evidence', exact: true }).click();
  await page.getByRole('button', { name: 'Upload private original', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Private incident evidence upload', exact: true }).getByRole('note', { name: /Private file saved\. Review its permission before attaching it\.$/ })).toBeVisible();
}
export async function permissionFields(page: Page) {
  await page.getByText('Record authorized source permission', { exact: true }).click();
  for (const [label, value] of Object.entries({ 'Private source rights holder': 'Fixture source holder', 'Private source permission basis': 'Explicit authored internal permission', 'Private source permitted purpose': 'Restricted incident documentation only', 'Private source use restrictions': 'No distribution' })) await page.getByRole('textbox', { name: label, exact: true }).fill(value);
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'Private source ingestion is authorized', exact: true }));
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'Private source reading is authorized', exact: true }));
  await page.getByRole('combobox', { name: 'Private source permission evidence', exact: true }).click();
  await page.getByRole('option', { name: `${document.title} · Rev. 1`, exact: true }).click();
  await page.getByRole('button', { name: 'Select private source permission evidence', exact: true }).click();
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I am authorized and reviewed this private source permission', exact: true }));
}
export async function recordPermission(page: Page) {
  await page.getByRole('button', { name: 'Record private source permission', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Private incident source permission', exact: true }).getByRole('note', { name: /Permission recorded\. Review the current permission before attaching the file\.$/ })).toBeVisible();
  await expect(page.getByRole('region', { name: 'Private incident source permission', exact: true }).getByRole('note', { name: /Current permission allows reading and importing today \(UTC\)/ })).toBeVisible();
}
export async function attachPrivate(page: Page) {
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed current private source permission for attachment', exact: true }));
  await page.getByRole('button', { name: 'Attach reviewed private source', exact: true }).click();
  await expect(page.getByRole('region', { name: 'Private incident source permission', exact: true }).getByRole('note', { name: /Private source selected for this incident/ })).toBeVisible();
}
