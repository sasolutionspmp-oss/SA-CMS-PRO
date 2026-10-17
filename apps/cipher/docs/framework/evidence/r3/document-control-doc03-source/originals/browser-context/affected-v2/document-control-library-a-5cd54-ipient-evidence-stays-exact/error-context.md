# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: document-control.spec.ts >> library adoption to issued set, internal distribution and recipient evidence stays exact
- Location: tests/document-control.spec.ts:18:1

# Error details

```
Test timeout of 90000ms exceeded.
```

```
Error: locator.click: Test timeout of 90000ms exceeded.
Call log:
  - waiting for locator('.engineering-object-page').getByRole('button', { name: 'Additional Options', exact: true })

```

# Page snapshot

```yaml
- generic [active]:
  - generic:
    - alert
    - alert
  - generic:
    - link "Skip to content" [ref=f6e1] [cursor=pointer]:
      - /url: "#main-content"
    - generic [ref=f6e3]:
      - banner [ref=f6e4]:
        - banner "Shell Bar" [ref=f6e6]:
          - button "Toggle navigation" [ref=f6e9] [cursor=pointer]
          - button "Cipher" [ref=f6e15] [cursor=pointer]:
            - generic [ref=f6e17]: Cipher The AEC/CMS Pro
          - generic [ref=f6e19]:
            - group "Additional Info" [ref=f6e20]:
              - generic [ref=f6e24] [cursor=pointer]:
                - combobox "Company" [ref=f6e26]: Document control fixture Company
                - generic: Document control fixture Company
              - generic [ref=f6e34]:
                - generic: Tag
                - generic: Synthetic workspace
            - search [ref=f6e40]:
              - generic [ref=f6e41]:
                - searchbox "Search projects" [ref=f6e42]
                - generic [ref=f6e43] [cursor=pointer]
            - button "Toggle Ricky assistant" [ref=f6e48] [cursor=pointer]
            - button [ref=f6e53] [cursor=pointer]:
              - img "Alex Author" [ref=f6e57]:
                - generic [ref=f6e58]: AA
      - generic [ref=f6e59]:
        - complementary [ref=f6e60]:
          - navigation "Cipher workspace navigation" [ref=f6e62]:
            - tree "Primary Navigation Menu" [ref=f6e63]:
              - generic:
                - treeitem "Projects" [ref=f6e65] [cursor=pointer]
                - treeitem "Project work" [ref=f6e71] [cursor=pointer]
                - treeitem "Estimates" [ref=f6e77] [cursor=pointer]
                - treeitem "Engineering" [ref=f6e83] [cursor=pointer]
                - treeitem "Drawing takeoff" [ref=f6e89] [cursor=pointer]
                - treeitem "Documents" [ref=f6e95] [cursor=pointer]
                - treeitem "Document control" [ref=f6e101] [cursor=pointer]
                - treeitem "Ricky" [ref=f6e107] [cursor=pointer]
            - separator [ref=f6e112]
            - tree "Footer Navigation Menu" [ref=f6e113]:
              - treeitem "Connections" [ref=f6e115] [cursor=pointer]
        - generic [ref=f6e122]:
          - generic [ref=f6e123]:
            - generic [ref=f6e124]:
              - generic [ref=f6e128]: Document control fixture Company
              - generic [ref=f6e129]: /
              - strong [ref=f6e130]: Cedar Valley Engineering
            - generic [ref=f6e131] [cursor=pointer]:
              - combobox "Project context" [ref=f6e133]: Cedar Valley Engineering
              - generic: All projects
              - generic: Cedar Valley Engineering
          - generic [ref=f6e138]:
            - toolbar "Document control navigation" [ref=f6e140]:
              - button "Library" [ref=f6e144] [cursor=pointer]
              - button "Issue sets" [ref=f6e150] [cursor=pointer]
              - button "Transmittals" [ref=f6e156] [cursor=pointer]
              - button "Adoptions" [ref=f6e162] [cursor=pointer]
              - button "Issued records" [ref=f6e168] [cursor=pointer]
              - button "Distributions" [ref=f6e174] [cursor=pointer]
              - button "Content permissions" [ref=f6e180] [cursor=pointer]
              - button "Receipt evidence" [ref=f6e186] [cursor=pointer]
              - button "Project documents" [ref=f6e192] [cursor=pointer]
            - generic [ref=f6e198]:
              - banner [ref=f6e199] [cursor=pointer]:
                - generic [ref=f6e201]:
                  - navigation "Breadcrumb Trail" [ref=f6e206]:
                    - list [ref=f6e207]:
                      - text: ...
                      - listitem [ref=f6e208]:
                        - link "Document control 1 of 2" [ref=f6e210]:
                          - generic [ref=f6e211]: Document control
                        - generic [aria-hidden] [ref=f6e212]: /
                      - listitem [ref=f6e213]:
                        - generic "Issued record 2 of 2": Issued record
                  - generic [ref=f6e219]:
                    - generic [ref=f6e220]:
                      - generic [ref=f6e221]:
                        - heading "Independently issued document set" [level=1] [ref=f6e223]
                        - group [ref=f6e225]:
                          - generic: Object Status
                          - generic [ref=f6e226]: Issued
                          - generic: Informative entry
                      - generic [ref=f6e227]: Issued record
                    - toolbar [ref=f6e230]:
                      - button "Refresh retained record" [ref=f6e234]
                      - button "Prepare internal transmittal" [ref=f6e243]
              - generic [ref=f6e249]:
                - generic [ref=f6e250]:
                  - generic [ref=f6e251]: Recorded by
                  - generic [ref=f6e252]: fixture.author@example.invalid
                - generic [ref=f6e253]:
                  - generic [ref=f6e254]: Recorded on
                  - generic [ref=f6e255]: Oct 17, 2026
                - generic [ref=f6e256]:
                  - generic [ref=f6e257]: Source standing
                  - generic [ref=f6e258]: Exact original retained
              - generic:
                - generic:
                  - button "Collapse Header" [expanded] [ref=f6e260] [cursor=pointer]
                  - button "Pin Header" [ref=f6e265] [cursor=pointer]
              - tablist [ref=f6e274]:
                - tab "Recorded details" [selected] [ref=f6e275] [cursor=pointer]
                - tab "Exact original documents" [ref=f6e278] [cursor=pointer]
                - tab "Retained related records" [ref=f6e281] [cursor=pointer]
              - generic [ref=f6e284]:
                - region [ref=f6e285]:
                  - heading "Recorded details" [level=3] [ref=f6e287]
                  - button "Review original document authorization" [ref=f6e293] [cursor=pointer]
                - region [ref=f6e297]:
                  - heading "Exact original documents" [level=3] [ref=f6e299]
                  - list [ref=f6e304]:
                    - listitem [ref=f6e305]:
                      - link "Original document · Revision 1" [ref=f6e307] [cursor=pointer]
                      - generic [ref=f6e309]: application/pdf · 523 bytes
                      - group [ref=f6e310]:
                        - generic "Original integrity" [ref=f6e311]
                - region [ref=f6e313]:
                  - heading "Retained related records" [level=3] [ref=f6e315]
                  - generic [ref=f6e320]:
                    - generic [ref=f6e322]:
                      - heading "Related retained records" [level=2] [ref=f6e325]
                      - button "Refresh document records" [ref=f6e329] [cursor=pointer]
                    - generic [ref=f6e335]:
                      - heading "No transmittal records yet" [level=3] [ref=f6e341]
                      - paragraph [ref=f6e343]: Only records available with current Project and original-source permissions appear here.
```

# Test source

```ts
  1  | import { expect, test, type Page } from '@playwright/test';
  2  | import { checkUi5Checkbox } from './ui5-controls';
  3  | import { controlPath, document, evidenceDocument, hash, mockDocumentControl, people, scope } from './document-control-fixture';
  4  | type Fixture = Awaited<ReturnType<typeof mockDocumentControl>>;
  5  | const recordPath = (kind: string, id: string) => `${controlPath}/record/${kind}/${id}`;
  6  | async function choose(page: Page, label: string, value: string) { await page.getByRole('combobox', { name: label, exact: true }).click(); await page.getByRole('option', { name: value, exact: true }).click(); }
> 7  | async function recordAction(page: Page, name: string) { const button = page.getByRole('button', { name, exact: true }); if (!await button.isVisible()) await page.locator('.engineering-object-page').getByRole('button', { name: 'Additional Options', exact: true }).click(); await page.getByRole('button', { name, exact: true }).click(); }
     |                                                                                                                                                                                                                                                                        ^ Error: locator.click: Test timeout of 90000ms exceeded.
  8  | async function source(page: Page, label: string, evidence = false) { const selected = evidence ? evidenceDocument : document; await choose(page, label, `${selected.title} · Rev. 1`); await page.getByRole('button', { name: `Select ${label.toLowerCase()}`, exact: true }).click(); }
  9  | async function reviewedSave(page: Page) { await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the document record', exact: true })); await page.getByRole('button', { name: 'Save document record', exact: true }).click(); }
  10 | async function libraryForm(page: Page, successor = false) { if (successor) await recordAction(page, 'Author library successor'); else await page.getByRole('button', { name: 'New library entry', exact: true }).click(); await page.getByRole('textbox', { name: 'Library title', exact: true }).fill(successor ? 'Concrete workmanship specification v2' : 'Concrete workmanship specification'); await page.getByRole('textbox', { name: 'Discipline', exact: true }).fill('Structural'); await page.getByRole('textbox', { name: 'Ownership', exact: true }).fill('Company authored specification'); await page.getByRole('textbox', { name: 'Library change reason', exact: true }).fill(successor ? 'Reviewed successor wording retained separately' : 'Initial exact original registration'); await source(page, 'Library source'); }
  11 | async function saved(page: Page) { const button = page.getByRole('button', { name: 'Open saved document record', exact: true }); await expect(button).toBeEnabled(); await button.click(); }
  12 | async function authorize(page: Page, fixture: Fixture) {
  13 |   await page.getByRole('button', { name: 'Request independent document authorization', exact: true }).click(); await expect(page.getByRole('dialog', { name: 'Independent document authorization', exact: true })).toBeVisible(); const id = [...fixture.packets.keys()].at(-1)!;
  14 |   fixture.setActor(1); await page.goto(`${controlPath}/approvals/${id}`); await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed this original document authorization', exact: true })); await page.getByRole('button', { name: 'Grant document authorization', exact: true }).click(); await expect.poll(() => fixture.packets.get(id).state).toBe('Granted'); await expect(page.getByRole('button', { name: 'Close document authorization', exact: true })).toBeEnabled();
  15 |   fixture.setActor(0); await page.reload(); await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed this original document authorization', exact: true })); await page.getByRole('button', { name: 'Record authorized document effect', exact: true }).click(); await expect.poll(() => fixture.packets.get(id).state).toBe('Consumed'); await expect(page.getByRole('button', { name: 'Close document authorization', exact: true })).toBeEnabled();
  16 | }
  17 | test.beforeEach(({ page }) => page.on('pageerror', error => { throw error; }));
  18 | test('library adoption to issued set, internal distribution and recipient evidence stays exact', async ({ page }) => {
  19 |   test.setTimeout(90000); const fixture = await mockDocumentControl(page); await page.goto(controlPath); await libraryForm(page); await reviewedSave(page); await saved(page); await expect(page.getByRole('heading', { name: 'Concrete workmanship specification', exact: true })).toBeVisible();
  20 |   await recordAction(page, 'Prepare Project adoption'); await page.getByRole('textbox', { name: 'Adoption purpose', exact: true }).fill('Apply the retained concrete specification to this Project'); await page.getByRole('textbox', { name: 'Target Project / contract locator', exact: true }).fill('Concrete package section 3'); await page.getByRole('textbox', { name: 'Adoption change reason', exact: true }).fill('Independent Project selection'); await reviewedSave(page); await saved(page); await authorize(page, fixture);
  21 |   const adoption = [...fixture.records.get('adoption')!.values()][0];
  22 |   await page.goto(`${controlPath}/register/issue_set`); await page.getByRole('button', { name: 'Prepare issue set', exact: true }).click(); await page.getByRole('textbox', { name: 'Issue set title', exact: true }).fill('Concrete coordination issue'); await page.getByRole('textbox', { name: 'Issue purpose', exact: true }).fill('Internal construction coordination'); await source(page, 'Issue documents'); await checkUi5Checkbox(page.getByRole('checkbox', { name: `Adopted library sources ${adoption.id}`, exact: true })); await reviewedSave(page); await saved(page); await authorize(page, fixture);
  23 |   const issue = [...fixture.records.get('issue')!.values()][0]; expect(issue.artifacts).toHaveLength(1); await page.goto(recordPath('issue', issue.id)); await recordAction(page, 'Prepare internal transmittal'); await page.getByRole('textbox', { name: 'Transmittal purpose', exact: true }).fill('Review the original concrete coordination issue'); await choose(page, 'Internal recipient', `${people[2].display_name} · ${people[2].user}`); await reviewedSave(page); await saved(page); await authorize(page, fixture);
  24 |   const distribution = [...fixture.records.get('distribution')!.values()][0]; fixture.setActor(2); await page.goto(recordPath('distribution', distribution.id)); await recordAction(page, 'Report receipt evidence'); await page.getByRole('textbox', { name: 'Reported observation', exact: true }).fill('I received and opened the retained document set.'); await source(page, 'Supporting evidence', true); await reviewedSave(page); await saved(page);
  25 |   expect([...fixture.records.get('evidence')!.values()][0]).toMatchObject({ author_person: people[2].person, status: 'reported_received', commercial_execution: false, electronic_signature: false, subject_id: distribution.id }); expect(fixture.writes.every(row => row.key === row.body.operation_id)).toBe(true); expect([...fixture.packets.values()].every(row => row.manifest_hash !== hash(row.review_manifest))).toBe(true);
  26 |   const library = [...fixture.records.get('library')!.values()][0], original = structuredClone(adoption); fixture.setActor(0); await page.goto(recordPath('library', library.id)); await libraryForm(page, true); await reviewedSave(page); await page.goto(recordPath('adoption', adoption.id)); await expect(page.getByText('The library or working source has a newer revision. This record retains the original adopted wording and bytes.', { exact: true })).toBeVisible(); expect(fixture.get('adoption', adoption.id)).toEqual(original);
  27 | });
  28 | test('content permission retains holder, purpose, dates and a separate evidence revision', async ({ page }) => {
  29 |   const fixture = await mockDocumentControl(page, { noRights: true }); await page.goto(`${controlPath}/register/rights`); await page.getByRole('button', { name: 'Record content permission', exact: true }).click(); await source(page, 'Governed document'); await page.getByRole('textbox', { name: 'Rights holder', exact: true }).fill('Project source author'); await page.getByRole('textbox', { name: 'Permission basis', exact: true }).fill('Permission evidence retained for this exact original'); await page.getByRole('textbox', { name: 'Permitted purpose', exact: true }).fill('Internal Project specification use'); await page.getByRole('textbox', { name: 'Effective from (YYYY-MM-DD, UTC)', exact: true }).fill('2026-10-16'); await page.getByRole('textbox', { name: 'Effective through (YYYY-MM-DD, UTC)', exact: true }).fill('2027-10-16'); for (const name of ['Ingest allowed', 'Read allowed', 'Distribute allowed']) await checkUi5Checkbox(page.getByRole('checkbox', { name, exact: true })); await source(page, 'Permission evidence', true); await reviewedSave(page); await saved(page);
  30 |   const rights = [...fixture.records.get('rights')!.values()][0]; expect(rights).toMatchObject({ rights_holder: 'Project source author', valid_from: '2026-10-16', valid_until: '2027-10-16', evidence_artifact: { revision_id: evidenceDocument.current_revision } }); expect(rights.evidence_artifact.document_id).not.toBe(rights.parent_id);
  31 | });
  32 | for (const loss of ['loseFirst', 'wrongFirst'] as const) test(`document request preserves original actor and UUID after ${loss}`, async ({ page }) => { const fixture = await mockDocumentControl(page, { [loss]: true }); await page.goto(controlPath); await libraryForm(page); await reviewedSave(page); const dialog = page.locator('ui5-dialog[header-text="New library entry"]'); await expect(dialog.getByRole('button', { name: 'Recover original document request', exact: true })).toBeVisible(); await expect(page.getByRole('combobox', { name: 'Company', exact: true, includeHidden: true })).toBeDisabled(); await dialog.getByRole('button', { name: 'Recover original document request', exact: true }).click(); await expect(dialog).not.toBeVisible(); expect(fixture.writes).toHaveLength(2); expect(fixture.writes[1].body).toEqual(fixture.writes[0].body); expect(fixture.records.get('library')!.size).toBe(1); });
  33 | test('current access denial removes previously loaded record and authoring controls', async ({ page }) => { const fixture = await mockDocumentControl(page); await page.goto(controlPath); await libraryForm(page); await reviewedSave(page); await saved(page); await expect(page.getByRole('grid', { name: 'Library revision records', exact: true })).toBeVisible(); fixture.setDenied(true); await page.getByRole('button', { name: 'Refresh retained record', exact: true }).click(); await expect(page.getByRole('button', { name: 'Recheck document-control access', exact: true })).toBeVisible(); await expect(page.getByRole('heading', { name: 'Concrete workmanship specification', exact: true })).toHaveCount(0); await expect(page.getByRole('button', { name: 'Author library successor', exact: true })).toHaveCount(0); });
  34 | for (const width of [1440, 900, 390]) test(`document authoring footer remains usable at ${width}px`, async ({ page }) => { await page.setViewportSize({ width, height: 1000 }); const fixture = await mockDocumentControl(page); await page.goto(controlPath); await libraryForm(page); await checkUi5Checkbox(page.getByRole('checkbox', { name: 'I reviewed the document record', exact: true })); const save = page.getByRole('button', { name: 'Save document record', exact: true }); await expect(save).toBeInViewport(); const bounds = await save.boundingBox(); expect(bounds!.x).toBeGreaterThanOrEqual(0); expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width); await save.click(); await expect(page.getByRole('button', { name: 'Open saved document record', exact: true })).toBeEnabled(); expect(fixture.records.get('library')!.size).toBe(1); });
  35 | 
```