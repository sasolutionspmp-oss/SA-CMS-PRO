# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: document-control.spec.ts >> document request preserves original actor and UUID after wrongFirst
- Location: tests/document-control.spec.ts:31:58

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('dialog', { name: 'New library entry', exact: true }).getByRole('button', { name: 'Recover original document request', exact: true })
Expected: visible
Timeout: 10000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('dialog', { name: 'New library entry', exact: true }).getByRole('button', { name: 'Recover original document request', exact: true }) with timeout 10000ms
  - waiting for getByRole('dialog', { name: 'New library entry', exact: true }).getByRole('button', { name: 'Recover original document request', exact: true })

```

```yaml
- alert
- alert
- link "Skip to content":
  - /url: "#main-content"
- banner:
  - banner "Shell Bar":
    - button "Toggle navigation"
    - button "Cipher": Cipher The AEC/CMS Pro
    - group "Additional Info":
      - combobox "Company" [disabled]: Document control fixture Company
      - text: Tag Synthetic workspace
    - search:
      - searchbox "Search projects"
    - button "Toggle Ricky assistant" [disabled]
    - button "Alex Author":
      - img "Alex Author": AA
- complementary:
  - navigation "Cipher workspace navigation":
    - tree "Primary Navigation Menu":
      - treeitem "Projects"
      - treeitem "Project work"
      - treeitem "Estimates"
      - treeitem "Engineering"
      - treeitem "Drawing takeoff"
      - treeitem "Documents"
      - treeitem "Document control"
      - treeitem "Ricky"
    - separator
    - tree "Footer Navigation Menu":
      - treeitem "Connections"
- text: Document control fixture Company /
- strong: Cedar Valley Engineering
- combobox "Project context" [disabled]: Cedar Valley Engineering
- alert:
  - note "Error Message Strip This reply could not be matched to the exact Project, original document revisions and reviewed request."
- note "Warning Message Strip The result is uncertain. Keep this view open and recover the original request before continuing."
- button "Recover original document request"
- toolbar "Document control navigation":
  - button "Library" [disabled]
  - button "Issue sets" [disabled]
  - button "Transmittals" [disabled]
  - button "Adoptions" [disabled]
  - button "Issued records" [disabled]
  - button "Distributions" [disabled]
  - button "Content permissions" [disabled]
  - button "Receipt evidence" [disabled]
  - button "Project documents" [disabled]
- banner:
  - text: PROJECT DOCUMENT CONTROL
  - heading "Library" [level=1]
  - paragraph: Retained specifications, adopted clauses, exact issued sets and internal distribution.
  - button "New library entry" [disabled]
- heading "Library entry register" [level=2]
- button "Refresh document records" [disabled]
- heading "No library entry records yet" [level=3]
- paragraph: Only records available with current Project and original-source permissions appear here.
- dialog "New library entry":
  - region "Header":
    - heading "New library entry" [level=1]
  - region "Content":
    - alert:
      - note "Error Message Strip This reply could not be matched to the exact Project, original document revisions and reviewed request."
    - note "Warning Message Strip The result is uncertain. Keep this view open and recover the original request before continuing."
    - button "Recover original document request"
    - text: Library title
    - textbox "Library title" [disabled]: Concrete workmanship specification
    - text: Library category
    - combobox "Library category" [disabled]: Specification
    - text: Discipline
    - textbox "Discipline" [disabled]: Structural
    - text: Ownership
    - textbox "Ownership" [disabled]: Company authored specification
    - text: Library change reason
    - textbox "Library change reason" [disabled]: Initial exact original registration
    - text: Tags (comma separated)
    - textbox "Tags (comma separated)" [disabled]
    - heading "Library source" [level=3]
    - text: Synthetic structural detail S-201 · Rev. 1
    - button "Remove Library source revision c83f2412-292f-490f-8a31-f6657f8e1b9e" [disabled]
    - text: Library source
    - combobox "Library source" [disabled]: Choose an existing document
    - button "Select library source" [disabled]
    - checkbox "I reviewed the document record" [checked] [disabled]: I reviewed these exact sources, fields and documentary effect
  - region "Footer":
    - toolbar "Header":
      - button "Save document record" [disabled]
      - button "Cancel" [disabled]
```

# Test source

```ts
  1  | import { expect, test, type Page } from '@playwright/test';
  2  | import { checkUi5Checkbox } from './ui5-controls';
  3  | import { controlPath, document, evidenceDocument, hash, mockDocumentControl, people, scope } from './document-control-fixture';
  4  | type Fixture = Awaited<ReturnType<typeof mockDocumentControl>>;
  5  | const recordPath = (kind: string, id: string) => `${controlPath}/record/${kind}/${id}`;
  6  | async function choose(page: Page, label: string, value: string) { await page.getByRole('combobox', { name: label, exact: true }).click(); await page.getByRole('option', { name: value, exact: true }).click(); }
  7  | async function source(page: Page, label: string, evidence = false) { const selected = evidence ? evidenceDocument : document; await choose(page, label, `${selected.title} · Rev. 1`); await page.getByRole('button', { name: `Select ${label.toLowerCase()}`, exact: true }).click(); }
  8  | async function reviewedSave(page: Page) { await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the document record', exact: true })); await page.getByRole('button', { name: 'Save document record', exact: true }).click(); }
  9  | async function libraryForm(page: Page, successor = false) { await page.getByRole('button', { name: successor ? 'Author library successor' : 'New library entry', exact: true }).click(); await page.getByRole('textbox', { name: 'Library title', exact: true }).fill(successor ? 'Concrete workmanship specification v2' : 'Concrete workmanship specification'); await page.getByRole('textbox', { name: 'Discipline', exact: true }).fill('Structural'); await page.getByRole('textbox', { name: 'Ownership', exact: true }).fill('Company authored specification'); await page.getByRole('textbox', { name: 'Library change reason', exact: true }).fill(successor ? 'Reviewed successor wording retained separately' : 'Initial exact original registration'); await source(page, 'Library source'); }
  10 | async function saved(page: Page) { const button = page.getByRole('button', { name: 'Open saved document record', exact: true }); await expect(button).toBeEnabled(); await button.click(); }
  11 | async function authorize(page: Page, fixture: Fixture) {
  12 |   await page.getByRole('button', { name: 'Request independent document authorization', exact: true }).click(); await expect(page.getByRole('dialog', { name: 'Independent document authorization', exact: true })).toBeVisible(); const id = [...fixture.packets.keys()].at(-1)!;
  13 |   fixture.setActor(1); await page.goto(`${controlPath}/approvals/${id}`); await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed this original document authorization', exact: true })); await page.getByRole('button', { name: 'Grant document authorization', exact: true }).click(); await expect.poll(() => fixture.packets.get(id).state).toBe('Granted'); await expect(page.getByRole('button', { name: 'Close document authorization', exact: true })).toBeEnabled();
  14 |   fixture.setActor(0); await page.reload(); await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed this original document authorization', exact: true })); await page.getByRole('button', { name: 'Record authorized document effect', exact: true }).click(); await expect.poll(() => fixture.packets.get(id).state).toBe('Consumed'); await expect(page.getByRole('button', { name: 'Close document authorization', exact: true })).toBeEnabled();
  15 | }
  16 | test.beforeEach(({ page }) => page.on('pageerror', error => { throw error; }));
  17 | test('library adoption to issued set, internal distribution and recipient evidence stays exact', async ({ page }) => {
  18 |   test.setTimeout(90000); const fixture = await mockDocumentControl(page); await page.goto(controlPath); await libraryForm(page); await reviewedSave(page); await saved(page); await expect(page.getByRole('heading', { name: 'Concrete workmanship specification', exact: true })).toBeVisible();
  19 |   await page.getByRole('button', { name: 'Prepare Project adoption', exact: true }).click(); await page.getByRole('textbox', { name: 'Adoption purpose', exact: true }).fill('Apply the retained concrete specification to this Project'); await page.getByRole('textbox', { name: 'Target Project / contract locator', exact: true }).fill('Concrete package section 3'); await page.getByRole('textbox', { name: 'Adoption change reason', exact: true }).fill('Independent Project selection'); await reviewedSave(page); await saved(page); await authorize(page, fixture);
  20 |   const adoption = [...fixture.records.get('adoption')!.values()][0];
  21 |   await page.goto(`${controlPath}/register/issue_set`); await page.getByRole('button', { name: 'Prepare issue set', exact: true }).click(); await page.getByRole('textbox', { name: 'Issue set title', exact: true }).fill('Concrete coordination issue'); await page.getByRole('textbox', { name: 'Issue purpose', exact: true }).fill('Internal construction coordination'); await source(page, 'Issue documents'); await checkUi5Checkbox(page.getByRole('checkbox', { name: `Adopted library sources ${adoption.id}`, exact: true })); await reviewedSave(page); await saved(page); await authorize(page, fixture);
  22 |   const issue = [...fixture.records.get('issue')!.values()][0]; expect(issue.artifacts).toHaveLength(1); await page.goto(recordPath('issue', issue.id)); await page.getByRole('button', { name: 'Prepare internal transmittal', exact: true }).click(); await page.getByRole('textbox', { name: 'Transmittal purpose', exact: true }).fill('Review the original concrete coordination issue'); await choose(page, 'Internal recipient', `${people[2].display_name} · ${people[2].user}`); await reviewedSave(page); await saved(page); await authorize(page, fixture);
  23 |   const distribution = [...fixture.records.get('distribution')!.values()][0]; fixture.setActor(2); await page.goto(recordPath('distribution', distribution.id)); await page.getByRole('button', { name: 'Report receipt evidence', exact: true }).click(); await page.getByRole('textbox', { name: 'Reported observation', exact: true }).fill('I received and opened the retained document set.'); await source(page, 'Supporting evidence', true); await reviewedSave(page); await saved(page);
  24 |   expect([...fixture.records.get('evidence')!.values()][0]).toMatchObject({ author_person: people[2].person, status: 'reported_received', commercial_execution: false, electronic_signature: false, subject_id: distribution.id }); expect(fixture.writes.every(row => row.key === row.body.operation_id)).toBe(true); expect([...fixture.packets.values()].every(row => row.manifest_hash !== hash(row.review_manifest))).toBe(true);
  25 |   const library = [...fixture.records.get('library')!.values()][0], original = structuredClone(adoption); fixture.setActor(0); await page.goto(recordPath('library', library.id)); await libraryForm(page, true); await reviewedSave(page); await page.goto(recordPath('adoption', adoption.id)); await expect(page.getByText('The library or working source has a newer revision. This record retains the original adopted wording and bytes.', { exact: true })).toBeVisible(); expect(fixture.get('adoption', adoption.id)).toEqual(original);
  26 | });
  27 | test('content permission retains holder, purpose, dates and a separate evidence revision', async ({ page }) => {
  28 |   const fixture = await mockDocumentControl(page, { noRights: true }); await page.goto(`${controlPath}/register/rights`); await page.getByRole('button', { name: 'Record content permission', exact: true }).click(); await source(page, 'Governed document'); await page.getByRole('textbox', { name: 'Rights holder', exact: true }).fill('Project source author'); await page.getByRole('textbox', { name: 'Permission basis', exact: true }).fill('Permission evidence retained for this exact original'); await page.getByRole('textbox', { name: 'Permitted purpose', exact: true }).fill('Internal Project specification use'); await page.getByRole('textbox', { name: 'Effective from (YYYY-MM-DD, UTC)', exact: true }).fill('2026-10-16'); await page.getByRole('textbox', { name: 'Effective through (YYYY-MM-DD, UTC)', exact: true }).fill('2027-10-16'); for (const name of ['Ingest allowed', 'Read allowed', 'Distribute allowed']) await checkUi5Checkbox(page.getByRole('checkbox', { name, exact: true })); await source(page, 'Permission evidence', true); await reviewedSave(page); await saved(page);
  29 |   const rights = [...fixture.records.get('rights')!.values()][0]; expect(rights).toMatchObject({ rights_holder: 'Project source author', valid_from: '2026-10-16', valid_until: '2027-10-16', evidence_artifact: { revision_id: evidenceDocument.current_revision } }); expect(rights.evidence_artifact.document_id).not.toBe(rights.parent_id);
  30 | });
> 31 | for (const loss of ['loseFirst', 'wrongFirst'] as const) test(`document request preserves original actor and UUID after ${loss}`, async ({ page }) => { const fixture = await mockDocumentControl(page, { [loss]: true }); await page.goto(controlPath); await libraryForm(page); await reviewedSave(page); const dialog = page.getByRole('dialog', { name: 'New library entry', exact: true }); await expect(dialog.getByRole('button', { name: 'Recover original document request', exact: true })).toBeVisible(); await expect(page.getByRole('combobox', { name: 'Company', exact: true })).toBeDisabled(); await dialog.getByRole('button', { name: 'Recover original document request', exact: true }).click(); await expect(dialog).not.toBeVisible(); expect(fixture.writes).toHaveLength(2); expect(fixture.writes[1].body).toEqual(fixture.writes[0].body); expect(fixture.records.get('library')!.size).toBe(1); });
     |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       ^ Error: expect(locator).toBeVisible() failed
  32 | test('current access denial removes previously loaded record and authoring controls', async ({ page }) => { const fixture = await mockDocumentControl(page); await page.goto(controlPath); await libraryForm(page); await reviewedSave(page); await saved(page); fixture.setDenied(true); await page.getByRole('button', { name: 'Refresh retained record', exact: true }).click(); await expect(page.getByRole('button', { name: 'Recheck document-control access', exact: true })).toBeVisible(); await expect(page.getByRole('heading', { name: 'Concrete workmanship specification', exact: true })).toHaveCount(0); await expect(page.getByRole('button', { name: 'Author library successor', exact: true })).toHaveCount(0); });
  33 | for (const width of [1440, 900, 390]) test(`document authoring footer remains usable at ${width}px`, async ({ page }) => { await page.setViewportSize({ width, height: 1000 }); const fixture = await mockDocumentControl(page); await page.goto(controlPath); await libraryForm(page); await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the document record', exact: true })); const save = page.getByRole('button', { name: 'Save document record', exact: true }); await expect(save).toBeInViewport(); const bounds = await save.boundingBox(); expect(bounds!.x).toBeGreaterThanOrEqual(0); expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width); await save.click(); await expect(page.getByRole('button', { name: 'Open saved document record', exact: true })).toBeEnabled(); expect(fixture.records.get('library')!.size).toBe(1); });
  34 | 
```