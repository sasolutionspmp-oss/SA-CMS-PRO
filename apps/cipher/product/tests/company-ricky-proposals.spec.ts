import { expect, test, type Page } from '@playwright/test';
import { citation, ids, openSuggestions, scopeInputs, selectOption, suggestionFixture, evidence } from './company-ricky-proposals-fixture';
import { company } from './fixture';

const review = (page:Page) => page.getByRole('region',{name:'Saved suggestion review',exact:true});
const prepareScope = async (page:Page) => { await scopeInputs(page); await page.getByRole('button',{name:'Prepare scope suggestion',exact:true}).click(); };

test('Company saved-suggestion mode is explicit beside unchanged Company reads',async({page})=>{
  const state=await suggestionFixture(page);await openSuggestions(page);
  await expect(page.getByText('Deterministic preparation; no model call.',{exact:false})).toBeVisible();
  await page.getByRole('button',{name:'Company reads',exact:true}).click();
  await expect(page.getByRole('complementary',{name:'Ricky Company assistant',exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Run selected read',exact:true})).toBeVisible();expect(state.requests).toEqual([]);
});

test('scope preparation retains authored sections, evidence and exact current working revision',async({page})=>{
  const state=await suggestionFixture(page,{paged:true});await openSuggestions(page);await scopeInputs(page,{paged:true});
  await page.getByRole('textbox',{name:'Scope heading 1',exact:true}).fill('Drainage scope');
  await page.getByRole('button',{name:'Prepare scope suggestion',exact:true}).click();
  await expect(review(page)).toBeVisible();await expect(review(page).getByRole('heading',{name:'Drainage scope',exact:true})).toBeVisible();
  await expect(review(page).getByText('Review window expired. Authorized historical review remains available.',{exact:false})).toBeVisible();
  expect(state.requests).toHaveLength(1);const request=state.requests[0].body.request as {arguments:Record<string,unknown>;sources:unknown[]};
  expect(request.arguments).toEqual({proposal_revision_id:ids.commercialRevision,sections:[{heading:'Drainage scope',text:'Review the drainage work from the original source.',citation_ids:[citation.id]}],unverified_claims:['Verify access conditions.']});expect(request.sources).toHaveLength(1);
  await expect(page.getByRole('button',{name:/^(Apply|Accept|Save to estimate|Configure model)$/})).toHaveCount(0);
  await review(page).getByRole('link',{name:'Original source specification · Rev. 1 · Page 1',exact:true}).click();
  await expect(page).toHaveURL(new RegExp(`/company/documents/${citation.document_id}/revisions/${citation.revision_id}\\?company=${company}&page=1`));
  expect(state.effects()).toBe(1);
});

test('estimate preparation selects canonical saved quantities and renders exact rational values with original units',async({page})=>{
  const state=await suggestionFixture(page);await openSuggestions(page);await selectOption(page,'Company suggestion type','Prepare estimate suggestion');
  await selectOption(page,'Suggestion pursuit','Selected waterworks pursuit');await selectOption(page,'Suggestion working record','Working drainage estimate');
  await selectOption(page,'Suggestion target line','Saved drainage length · 1.000000000001');await selectOption(page,'Suggestion quantity source','Saved drainage length · 1.000000000001');
  await expect(page.getByText('Target line unit: Metre · m.',{exact:false})).toBeVisible();await page.getByRole('button',{name:'Add selected quantity',exact:true}).click();
  await page.getByRole('textbox',{name:'Suggestion estimate notes',exact:true}).fill('Keep the original rational quantity for review.');await evidence(page);
  await page.getByRole('button',{name:'Prepare estimate suggestion',exact:true}).click();await expect(review(page)).toBeVisible();
  await expect(review(page).getByText('1000000000001 / 1000000000000 Metre · m',{exact:true})).toBeVisible();await expect(review(page).getByText('Keep the original rational quantity for review.',{exact:true})).toBeVisible();
  expect(state.requests).toHaveLength(1);expect(state.requests[0].body.request).toMatchObject({action:'aec.estimate.draft',arguments:{base_revision_id:ids.estimateRevision,selections:[{line_record_id:ids.line,source_kind:'estimate-line',source_id:ids.line,target_unit_id:ids.unit}]},measurement_ids:[]});
});

for(const wrongAdmission of [false,true])test(`${wrongAdmission?'terminal admission mismatch':'lost Start response'} retains original UUID and blocks mode/close until exact queued replay`,async({page})=>{
  const state=await suggestionFixture(page,{lostStart:!wrongAdmission,wrongAdmission});await openSuggestions(page);await prepareScope(page);
  const recover=page.getByRole('button',{name:'Recover original suggestion request',exact:true});await expect(recover).toBeEnabled();
  await expect(page.getByRole('button',{name:'Company reads',exact:true})).toBeDisabled();await expect(page.getByRole('button',{name:'Close Ricky',exact:true})).toBeDisabled();await expect(page.getByRole('button',{name:'Toggle Ricky assistant',exact:true})).toBeDisabled();await expect(page.getByRole('button',{name:'Prepare scope suggestion',exact:true})).toBeDisabled();
  await recover.click();await expect(review(page)).toBeVisible();expect(state.requests).toHaveLength(2);expect(state.requests[1]).toEqual(state.requests[0]);expect(state.effects()).toBe(1);
});

test('lost source-free Stop retains original UUID while denied full reads cannot be initialized by its narrow receipt',async({page})=>{
  const state=await suggestionFixture(page,{pointer:true,active:true,lostStop:true});await openSuggestions(page);await expect(page.getByText('Saved Company request',{exact:true})).toBeVisible();state.setDenied(true);
  await page.getByRole('button',{name:'Refresh suggestion access',exact:true}).click();await expect(page.getByRole('note',{name:/You don’t have access to this item\./})).toBeVisible();
  await page.getByRole('button',{name:'Stop this request',exact:true}).click();await expect(page.getByRole('button',{name:'Recover original Stop',exact:true})).toBeEnabled();await expect(page.getByRole('button',{name:'Company reads',exact:true})).toBeDisabled();await expect(page.getByRole('button',{name:'Close Ricky',exact:true})).toBeDisabled();await expect(page.getByRole('button',{name:'Toggle Ricky assistant',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'Recover original Stop',exact:true}).click();await expect(page.getByText('Stop confirmed: Cancelled.',{exact:false})).toBeVisible();await expect(review(page)).toHaveCount(0);expect(state.requests).toHaveLength(2);expect(state.requests[1]).toEqual(state.requests[0]);
});

test('current source denial removes an observed suggestion while terminal Stop never claims cancellation',async({page})=>{
  const state=await suggestionFixture(page,{pointer:true});await openSuggestions(page);await expect(review(page)).toBeVisible();state.setDenied(true);
  await page.getByRole('button',{name:'Refresh suggestion access',exact:true}).click();await expect(page.getByRole('note',{name:/You don’t have access to this item\./})).toBeVisible();await expect(review(page)).toHaveCount(0);await expect(page.getByText(citation.excerpt,{exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Stop this request',exact:true}).click();await expect(page.getByText('Stop confirmed: Waiting for review.',{exact:false})).toBeVisible();await expect(review(page)).toHaveCount(0);expect(state.current().run.status).toBe('waiting-for-review');
  state.setDenied(false);await page.getByRole('button',{name:'Refresh suggestion access',exact:true}).click();await expect(review(page)).toBeVisible();
});

for(const target of ['Run','suggestion'] as const)test(`changed terminal ${target} fails closed after a valid original observation`,async({page})=>{
  const state=await suggestionFixture(page,{pointer:true});await openSuggestions(page);await expect(review(page)).toBeVisible();
  if(target==='Run')state.mutateRun({created_at:'2020-10-15T00:00:00Z'});else state.mutateProposal({expires_at:'2020-10-17T00:00:00Z'});
  await page.getByRole('button',{name:'Refresh suggestion access',exact:true}).click();await expect(page.getByRole('note', { name: /We couldn’t confirm the result\./ })).toBeVisible(); await page.locator('.support-details').filter({ hasText: /This saved suggestion or its original sources could not be verified/ }).locator('summary').click(); await expect(page.locator('.support-details[open] > p').filter({ hasText: /This saved suggestion or its original sources could not be verified/ })).toBeVisible();
  await expect(review(page)).toHaveCount(0);expect(state.requests).toEqual([]);
});

test('historical estimate review uses the retained base after its working head advances',async({page})=>{
  const state=await suggestionFixture(page,{pointer:true,action:'aec.estimate.draft'});state.advanceHeads();await openSuggestions(page);await expect(review(page)).toBeVisible();
  expect(state.reads.filter(row=>row.record_id===ids.successor)).toEqual([]);expect(state.reads.some(row=>row.record_id===ids.estimateRevision)).toBe(true);await expect(review(page).getByText('1000000000001 / 1000000000000 Metre · m',{exact:true})).toBeVisible();expect(state.requests).toEqual([]);
});

test('same-Person alias reload and Company switch do not reopen another identity pointer',async({page})=>{
  const state=await suggestionFixture(page,{pointer:true,twoCompanies:true});await openSuggestions(page);await expect(review(page)).toBeVisible();
  state.alias();await page.reload();await page.getByRole('button',{name:'Toggle Ricky assistant',exact:true}).click();await page.getByRole('button',{name:'Saved suggestions',exact:true}).click();await expect(review(page)).toHaveCount(0);await expect(page.getByRole('combobox',{name:'Suggestion pursuit',exact:true})).toBeVisible();
  const before=state.reads.length;await selectOption(page,'Company','Company B');await expect(page.getByRole('complementary',{name:'Ricky Company assistant',exact:true})).toBeVisible();await page.getByRole('button',{name:'Saved suggestions',exact:true}).click();await expect(review(page)).toHaveCount(0);
  expect(state.reads.slice(before).filter(row=>row.method.startsWith('cipher_aec.ricky.company_proposal_api.'))).toEqual([]);expect(state.requests).toEqual([]);
});

for(const width of [1440,900,390])test(`official suggestion controls and readable review fit ${width}px`,async({page},testInfo)=>{
  await page.setViewportSize({width,height:1000});const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));page.on('response',response=>{if(response.status()>=400)errors.push(`${response.status()} ${response.url()}`);});
  await suggestionFixture(page);await openSuggestions(page);await prepareScope(page);await expect(review(page)).toBeVisible();const panel=page.getByRole('complementary',{name:'Company saved suggestions',exact:true});
  const bounds=await panel.evaluate(element=>{const box=element.getBoundingClientRect();return{left:box.left,right:box.right,viewport:innerWidth,scroll:element.scrollWidth,width:element.clientWidth};});expect(bounds.left).toBeGreaterThanOrEqual(-1);expect(bounds.right).toBeLessThanOrEqual(bounds.viewport+1);expect(bounds.scroll).toBeLessThanOrEqual(bounds.width+1);
  await expect(page.getByRole('button',{name:'Stop this request',exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'Close Ricky',exact:true})).toBeVisible();await panel.screenshot({path:testInfo.outputPath(`mocked-suggestion-review-${width}.png`)});expect(errors).toEqual([]);
});


test('changed selected working head is refused before any suggestion command',async({page})=>{
  const state=await suggestionFixture(page);await openSuggestions(page);await selectOption(page,'Suggestion pursuit','Selected waterworks pursuit');
  await expect(page.getByRole('combobox',{name:'Suggestion working record',exact:true})).toBeEnabled();state.advanceHeads();await selectOption(page,'Suggestion working record','Working commercial draft');
  await expect(page.getByRole('note', { name: /We couldn’t confirm the result\./ })).toBeVisible(); await page.locator('.support-details').filter({ hasText: /This saved suggestion or its original sources could not be verified/ }).locator('summary').click(); await expect(page.locator('.support-details[open] > p').filter({ hasText: /This saved suggestion or its original sources could not be verified/ })).toBeVisible();await expect(page.getByRole('button',{name:'Prepare scope suggestion',exact:true})).toBeDisabled();expect(state.requests).toEqual([]);
});

test('long authored review text and optional integrity details remain contained on phone',async({page})=>{
  await page.setViewportSize({width:390,height:1000});await suggestionFixture(page);await openSuggestions(page);await scopeInputs(page);
  await page.getByRole('textbox',{name:'Scope heading 1',exact:true}).fill('W'.repeat(200));await page.getByRole('textbox',{name:'Scope text 1',exact:true}).fill('Z'.repeat(1500));await page.getByRole('button',{name:'Prepare scope suggestion',exact:true}).click();await expect(review(page)).toBeVisible();
  await page.getByText('Original selection and integrity details',{exact:true}).click();
  const sizes=await review(page).evaluate(element=>({width:element.clientWidth,scroll:element.scrollWidth}));expect(sizes.scroll).toBeLessThanOrEqual(sizes.width+1);
});
