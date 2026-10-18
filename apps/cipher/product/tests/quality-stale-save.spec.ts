import { expect, test, type Page } from '@playwright/test';
import { checkUi5Checkbox } from './ui5-controls';
import { hash } from './field-fixture';
import { mockQuality, qualityPath } from './quality-safety-fixture';

async function review(page: Page) {
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the quality record', exact: true }));
}

// Fixture acceptance only. The local source-state proof does not execute these
// tests: root must run them with the existing cached React/Chromium environment.
for (const family of ['record', 'incident']) test(`known 412 permits an intentional reviewed ${family} successor after cancel, refresh and current-record reopen`, async ({ page }) => {
  const fixture = await mockQuality(page, { staleFirst: true }), seed = fixture.seed(family);
  const revisionKind = family === 'incident' ? 'incident_revision' : 'revision';
  await page.goto(qualityPath(family, seed.header.id));
  await page.getByRole('button', { name: 'Create revision', exact: true }).click();
  await page.getByRole('textbox', { name: 'Description', exact: true }).fill('Attempt preserved until explicit cancellation.');
  await review(page);
  const save = page.getByRole('button', { name: 'Save record', exact: true });
  await save.click();
  await expect(save).toBeDisabled();
  await expect(page.getByRole('textbox', { name: 'Description', exact: true })).toHaveValue('Attempt preserved until explicit cancellation.');
  await expect(page.getByText(/Your entries are saved here/)).toBeVisible();
  expect(fixture.writes).toHaveLength(1);

  // Another actor's current immutable revision is visible only after an explicit
  // fresh read; the stale form is never silently rebased onto it.
  const currentRevision = { ...seed.revision, id: crypto.randomUUID(), revision_number: 2, predecessor: seed.revision.id, definition: { ...seed.revision.definition, description: 'Current revision from the concurrent reviewer.' } };
  const currentHeader = { ...seed.header, revision_number: 2, current_revision: currentRevision.id };
  fixture.put(revisionKind, currentRevision);
  fixture.put(family, currentHeader);
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.getByText(currentRevision.definition.description, { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Refresh record', exact: true }).click();
  await expect(page.getByText(currentRevision.definition.description, { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Create revision', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Description', exact: true })).toHaveValue(currentRevision.definition.description);
  await expect(page.getByRole('checkbox', { name: 'I reviewed the quality record', exact: true })).not.toBeChecked();
  await expect(save).toBeDisabled();
  expect(fixture.writes).toHaveLength(1);
  await page.getByRole('textbox', { name: 'Description', exact: true }).fill('An intentionally reviewed successor to the fresh current revision.');
  await review(page);
  await expect(save).toBeEnabled();
  expect(fixture.writes).toHaveLength(1);
  await save.click();
  await expect(page.getByRole('button', { name: 'Open saved record', exact: true })).toBeVisible();
  expect(fixture.writes).toHaveLength(2);
  expect(fixture.writes[1].body.expected_version).toBe(hash(currentHeader));
  expect(fixture.writes[1].body.operation_id).not.toBe(fixture.writes[0].body.operation_id);
  expect(fixture.writes[1].key).toBe(fixture.writes[1].body.operation_id);
  const saved = fixture.get(family, seed.header.id), successor = fixture.get(revisionKind, saved.current_revision);
  expect(saved.revision_number).toBe(3);
  expect(successor.predecessor).toBe(currentRevision.id);
  expect(fixture.get(revisionKind, seed.revision.id)).toEqual(seed.revision);
  expect(fixture.get(revisionKind, currentRevision.id)).toEqual(currentRevision);
});

test('unknown result followed by 412 cannot use Cancel or a new editor to discard the original request', async ({ page }) => {
  const fixture = await mockQuality(page, { loseFirst: true }), seed = fixture.seed();
  await page.goto(qualityPath('record', seed.header.id));
  await page.getByRole('button', { name: 'Create revision', exact: true }).click();
  await page.getByRole('textbox', { name: 'Description', exact: true }).fill('Recover this exact successor only.');
  await review(page);
  await page.getByRole('button', { name: 'Save record', exact: true }).click();
  const recover = page.getByRole('button', { name: 'Recover original quality request', exact: true });
  await expect(recover).toBeEnabled();
  fixture.setDenied(412);
  await recover.click();
  await expect(page.getByText(/This record changed\. Refresh and review/).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'New record', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Save record', exact: true })).toBeDisabled();
  await expect(page.getByRole('combobox', { name: 'Company', exact: true })).toBeDisabled();
  await expect(page.getByRole('combobox', { name: 'Project context', exact: true })).toBeDisabled();
  expect(fixture.writes).toHaveLength(1);
  fixture.setDenied(0);
  await recover.click();
  await expect(page.getByRole('button', { name: 'Open saved record', exact: true })).toBeVisible();
  expect(fixture.writes).toHaveLength(2);
  expect(fixture.writes[1]).toEqual(fixture.writes[0]);
  expect(fixture.get('record', seed.header.id).revision_number).toBe(2);
});
