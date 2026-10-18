import { test, expect } from '@playwright/test';
import { checkUi5Checkbox } from './ui5-controls';
import { mockQuality, qualityPath } from './quality-safety-fixture';
import { incidentFields, uploadPrivate, permissionFields, recordPermission, attachPrivate } from './quality-incident-rights-fixture';

test('private upload remains metadata only until separate reviewed permission and attachment', async ({ page }) => {
  const fixture = await mockQuality(page); await page.goto(qualityPath('incident'));
  await page.getByRole('button', { name: 'New restricted incident', exact: true }).click(); await incidentFields(page); await uploadPrivate(page);
  expect(fixture.writes.map(row => row.method)).toEqual(['upload_evidence']); expect(fixture.rightsWrites).toHaveLength(0);
  await expect(page.getByRole('button', { name: 'Save record', exact: true })).toBeDisabled();
  await expect(page.getByRole('button', { name: 'Attach reviewed private source', exact: true })).toBeDisabled();
  await page.getByText('Record authorized source permission', { exact: true }).click();
  await expect(page.getByRole('checkbox', { name: 'Private source ingestion is authorized', exact: true })).not.toBeChecked();
  await expect(page.getByRole('checkbox', { name: 'Private source reading is authorized', exact: true })).not.toBeChecked();
  await expect(page.getByRole('button', { name: 'Record private source permission', exact: true })).toBeDisabled();
  await page.getByText('Record authorized source permission', { exact: true }).click();
  await permissionFields(page); expect(fixture.rightsWrites).toHaveLength(0); await recordPermission(page);
  expect(fixture.rightsWrites).toHaveLength(1); expect(fixture.rightsWrites[0].key).toBe(fixture.rightsWrites[0].body.operation_id);
  expect(fixture.rightsWrites[0].body.definition).toMatchObject({ ingest_allowed: true, read_allowed: true, distribute_allowed: false });
  await expect(page.getByRole('button', { name: 'Attach reviewed private source', exact: true })).toBeDisabled();
  await attachPrivate(page); expect(fixture.rightsWrites).toHaveLength(1); expect(fixture.writes).toHaveLength(1);
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the quality record', exact: true }));
  await page.getByRole('button', { name: 'Save record', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Open saved record', exact: true })).toBeVisible(); expect(fixture.writes.map(row => row.method)).toEqual(['upload_evidence', 'create_record']);
});

for (const loss of ['loseRightsFirst', 'wrongRightsFirst'] as const) test(`uncertain ${loss} preserves original rights command across denial and restores pending source without attaching`, async ({ page }) => {
  const fixture = await mockQuality(page, { [loss]: true }); await page.goto(qualityPath('incident'));
  await page.getByRole('button', { name: 'New restricted incident', exact: true }).click(); await incidentFields(page); await uploadPrivate(page); await permissionFields(page);
  await page.getByRole('button', { name: 'Record private source permission', exact: true }).click();
  const recover = page.getByRole('button', { name: 'Recover original quality request', exact: true }); await expect(recover).toBeEnabled();
  await expect(page.getByRole('button', { name: 'Cancel', exact: true })).toBeDisabled();
  await expect(page.getByRole('combobox', { name: 'Company', exact: true })).toBeDisabled();
  fixture.setRightsDenied(403); await recover.click(); await expect(recover).toBeEnabled();
  await expect(page.getByText('SENSITIVE SERVER REASON MUST NEVER BE SHOWN', { exact: true })).toHaveCount(0);
  await expect(page.getByRole('textbox', { name: 'Restricted account', exact: true })).toHaveCount(0);
  fixture.setRightsDenied(0); await recover.click(); await expect(recover).toHaveCount(0);
  expect(fixture.rightsWrites).toHaveLength(2); expect(fixture.rightsWrites[1]).toEqual(fixture.rightsWrites[0]);
  await page.getByRole('button', { name: 'New restricted incident', exact: true }).click(); await incidentFields(page);
  await expect(page.getByText(/Current permission allows reading and importing today \(UTC\)/)).toBeVisible();
  await expect(page.getByRole('checkbox', { name: 'I reviewed current private source permission for attachment', exact: true })).not.toBeChecked();
  await expect(page.getByRole('button', { name: 'Attach reviewed private source', exact: true })).toBeDisabled();
  await attachPrivate(page); expect(fixture.writes).toHaveLength(1);
});

test('known stale rights require fresh policy review and an intentional new request', async ({ page }) => {
  const fixture = await mockQuality(page, { staleRightsFirst: true }); await page.goto(qualityPath('incident'));
  await page.getByRole('button', { name: 'New restricted incident', exact: true }).click(); await incidentFields(page); await uploadPrivate(page); await permissionFields(page);
  await page.getByRole('button', { name: 'Record private source permission', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Private source rights holder', exact: true })).toHaveValue('Fixture source holder');
  expect(fixture.rightsWrites).toHaveLength(1);
  await expect(page.getByRole('checkbox', { name: 'I am authorized and reviewed this private source permission', exact: true })).not.toBeChecked();
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I am authorized and reviewed this private source permission', exact: true }));
  await expect(page.getByRole('button', { name: 'Record private source permission', exact: true })).toBeDisabled();
  expect(fixture.rightsWrites).toHaveLength(1);
  await page.getByRole('button', { name: 'Refresh private source permission', exact: true }).click();
  await expect(page.getByText(/Current permission allows reading and importing today \(UTC\)/)).toBeVisible();
  await expect(page.getByRole('checkbox', { name: 'I am authorized and reviewed this private source permission', exact: true })).not.toBeChecked();
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I am authorized and reviewed this private source permission', exact: true }));
  await recordPermission(page); expect(fixture.rightsWrites).toHaveLength(2);
  expect(fixture.rightsWrites[1].body.operation_id).not.toBe(fixture.rightsWrites[0].body.operation_id);
  expect(fixture.rightsWrites[1].body.expected_version).toMatch(/^[a-f0-9]{64}$/); await attachPrivate(page);
});

for (const change of ['permission', 'source']) test(`attachment checks current ${change} again instead of using cached admission`, async ({ page }) => {
  const fixture = await mockQuality(page); await page.goto(qualityPath('incident'));
  await page.getByRole('button', { name: 'New restricted incident', exact: true }).click(); await incidentFields(page); await uploadPrivate(page); await permissionFields(page); await recordPermission(page);
  const id = [...fixture.privateDocuments.keys()][0];
  if (change === 'permission') fixture.putPolicy(id, { ...fixture.currentPolicy(id), ingest_allowed: false });
  else fixture.privateDocuments.get(id)!.document.current_revision = 'a-newer-source-revision';
  await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed current private source permission for attachment', exact: true }));
  await page.getByRole('button', { name: 'Attach reviewed private source', exact: true }).click();
  await expect(page.getByText(/The current source or permission changed/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Save record', exact: true })).toBeDisabled(); expect(fixture.rightsWrites).toHaveLength(1); expect(fixture.writes).toHaveLength(1);
});

test('missing current Document control duty leaves stored private original pending without permission controls', async ({ page }) => {
  const fixture = await mockQuality(page); fixture.projects.forEach(p => { p.capabilities = p.capabilities.filter(c => c !== 'document.control.read'); });
  await page.goto(qualityPath('incident')); await page.getByRole('button', { name: 'New restricted incident', exact: true }).click(); await incidentFields(page); await uploadPrivate(page);
  await expect(page.getByText(/An evidence manager with Document control access/)).toBeVisible();
  await expect(page.getByRole('button', { name: 'Record private source permission', exact: true })).toHaveCount(0); expect(fixture.rightsWrites).toHaveLength(0);
});
