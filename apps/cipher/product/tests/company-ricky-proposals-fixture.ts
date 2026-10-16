// Browser contracts only. Product source never imports or falls back to fixtures.
import { createHash } from 'node:crypto';
import { expect, type Page, type Route } from '@playwright/test';
import { company, mockWorkspace } from './fixture';
import { canonicalSuggestionJSON, suggestionPointerKey } from '../src/api/company-ricky-proposals-validation';
import type { CompanyRickyProposalSelection as Selection, CompanyRickyProposalResponse as Proposal, CompanyRickyProposalRunResponse as Run } from '../src/api/company-ricky-proposals.generated';
import type { CompanyCitation } from '../src/api/company-documents.generated';

export const id = (value: number) => `00000000-0000-4000-8000-${String(value).padStart(12, '0')}`;
export const digest = (value: unknown) => createHash('sha256').update(canonicalSuggestionJSON(value)).digest('hex');
export const ids = { pursuit:id(1), commercial:id(2), commercialRevision:id(3), estimate:id(4), estimateRevision:id(5), snapshot:id(6), line:id(7), unit:id(8), successor:id(9), measurement:id(10), scopeRun:id(11), estimateRun:id(12), proposal:id(13), step:id(14), invocation:id(15) };
export const citation: CompanyCitation = {id:'9'.repeat(64),document_id:'DOC-'+'1'.repeat(32),revision_id:'REV-'+'2'.repeat(32),document_title:'Original source specification',revision_number:1,page:1,page_label:'Page 1',excerpt:'Use the retained original specification and confirm the scope.',excerpt_sha256:'7'.repeat(64),source_sha256:'8'.repeat(64),company,scope_type:'Company',project:null};
export const unit = {id:ids.unit,kind:'uom',revision:1,fields:{symbol:'m',dimension:'length',precision:12},target:{doctype:'UOM',name:'Metre'}};
export const unitManifest = {schema:'cipher.canonical.v2',dataset_id:id(20),scope:{scope_type:'Company',company,project:null},records:[unit],unit_conversions:[]};
export const line = {id:ids.line,company,scope_type:'Company',project:null,estimate:ids.estimate,estimate_revision:ids.estimateRevision,line_id:id(21),authored:{description:'Saved drainage length',quantity:{amount:'1.000000000001',unit_id:ids.unit,precision:12}}};
export const sourceReference = {citation_id:citation.id,revision_id:citation.revision_id,page:citation.page,excerpt_sha256:citation.excerpt_sha256,source_sha256:citation.source_sha256};

export function selection(action: Selection['action'] = 'aec.scope.draft'): Selection {
  return {schema:'cipher.ricky.company.proposal-request.v1',pursuit_id:ids.pursuit,action,arguments:action==='aec.scope.draft'?{proposal_revision_id:ids.commercialRevision,sections:[{heading:'Suggested scope',text:'Review the drainage work from the original source.',citation_ids:[citation.id]}],unverified_claims:['Verify access conditions.']}:{base_revision_id:ids.estimateRevision,selections:[{line_record_id:ids.line,source_kind:'estimate-line',source_id:ids.line,target_unit_id:ids.unit}],notes:'Review this existing canonical quantity.',citation_ids:[citation.id],unverified_claims:[]},sources:[sourceReference],measurement_ids:[]} as Selection;
}

export function saved(action: Selection['action'] = 'aec.scope.draft', chosen = selection(action)) {
  const scope=action==='aec.scope.draft';const revision=scope?String(chosen.arguments.proposal_revision_id):String(chosen.arguments.base_revision_id);
  const owner=scope?ids.commercial:ids.estimate;const revisionDigest=digest({revision});const ownerDigest=digest({owner});const pursuitDigest=digest({pursuit:ids.pursuit});const snapshotDigest=digest({snapshot:ids.snapshot});
  const records:Record<string,unknown>[]=[{domain:scope?'commercial':'estimate',kind:scope?'proposal-revision':'revision',id:revision,digest:revisionDigest}];
  if(!scope) records.push({domain:'estimate',kind:'snapshot',id:ids.snapshot,digest:snapshotDigest},{domain:'estimate',kind:'line',id:ids.line,digest:digest(line)});
  const manifest={schema:'cipher.ricky.company.original-proposal.v1',selection_digest:digest(chosen),action_complete:true,pursuit:{id:ids.pursuit,digest:pursuitDigest,party_type:'Customer',party_id:'Fixture Customer',opportunity:'Fixture Opportunity',native_refs:[{doctype:'Customer',name:'Fixture Customer'},{doctype:'Opportunity',name:'Fixture Opportunity'}]},citations:[{id:citation.id,digest:digest(citation)}],records:records.sort((a,b)=>String(a.domain).localeCompare(String(b.domain))||String(a.kind).localeCompare(String(b.kind))||String(a.id).localeCompare(String(b.id))),owners:[{domain:scope?'commercial':'estimate',kind:scope?'proposal':'estimate',id:owner,pursuit_id:ids.pursuit,digest:ownerDigest}],preparation_heads:[{domain:scope?'commercial':'estimate',owner_id:owner,revision_id:revision,digest:revisionDigest}],qualified_units:scope?[]:[{id:ids.unit,digest:digest(unit)}],quantity_standing:[]};
  const dependencies=scope?[{kind:'pursuit',id:ids.pursuit,digest:pursuitDigest},{kind:'proposal',id:owner,digest:ownerDigest},{kind:'proposal-revision',id:revision,digest:revisionDigest}]:[{kind:'estimate-revision',id:revision,digest:revisionDigest},{kind:'calculation-snapshot',id:ids.snapshot,digest:snapshotDigest},{kind:'estimate',id:owner,digest:ownerDigest},{kind:'pursuit',id:ids.pursuit,digest:pursuitDigest}];
  const preparation:Record<string,unknown>={scope_type:'Company',company,pursuit_id:ids.pursuit,persistent:false,review_required:true,claim_classification:'unverified-author-suggestion',verified_source_references:[{...sourceReference,document_id:citation.document_id,canonical_digest:digest(citation)}],unverified_claims:chosen.arguments.unverified_claims,record_dependencies:dependencies,kind:scope?'scope-draft.v1':'estimate-draft.v1',proposed_fields:scope?{sections:chosen.arguments.sections}:{quantity_selections:(chosen.arguments.selections as {line_record_id:string;source_kind:string;source_id:string;target_unit_id:string}[]).map(row=>({line_record_id:row.line_record_id,quantity:{source_kind:row.source_kind,source_id:row.source_id,source_digest:digest(line),source_unit_id:ids.unit,target_unit_id:row.target_unit_id,numerator:'1000000000001',denominator:'1000000000000',provenance:'authored-estimate-line',quantity_basis:'authored-line-v1',independently_verified:false,eligible_for_new_use:true,model_supplied_quantity:false}})),notes:chosen.arguments.notes}};
  preparation.draft_digest=digest(preparation);const preparationDigest=digest(preparation);const proposalId=scope?ids.proposal:id(23);const runId=scope?ids.scopeRun:ids.estimateRun;
  const proposal={id:proposalId,company,scope_type:'Company',project:null,created_at:'2020-10-16T00:00:01Z',schema:'cipher.ricky.company.proposal.v1',run_id:runId,status:'proposed',version:1,persistent:true,action,action_version:'1',kind:scope?'scope-draft.v1':'estimate-draft.v1',step_id:ids.step,invocation_id:ids.invocation,expires_at:'2020-10-16T00:05:00Z',content_digest:digest({originalStoredWrapper:proposalId,preparationDigest}),preparation_digest:preparationDigest,preparation:structuredClone(preparation),source_manifest:manifest,prepared_manifest_digest:digest(manifest),review_required:true,claim_classification:'unverified-author-suggestion'} as unknown as Proposal;
  const result={proposal_id:proposal.id,proposal_version:1 as const,proposal_digest:proposal.content_digest,preparation_digest:proposal.preparation_digest};
  const run:Run={id:runId,company,scope_type:'Company',project:null,request_kind:'deterministic-proposal-v1',status:'waiting-for-review',cancel_requested:false,created_at:'2020-10-16T00:00:00Z',completed_at:'2020-10-16T00:00:01Z',action,result,result_digest:digest(result),error:null,standing:{mode:'deterministic-proposal-v1',model_invoked:false,live_model_qualified:false},result_basis:'persisted-proposal-reference-v1',selection:chosen,selection_digest:digest(chosen)};
  const events={items:[{id:ids.step,run_id:runId,status:'succeeded',tool_name:action,created_at:'2020-10-16T00:00:00Z',completed_at:'2020-10-16T00:00:01Z',error:null}]};
  return {run,proposal,events};
}

export async function suggestionFixture(page:Page,options:{lostStart?:boolean;lostStop?:boolean;pointer?:boolean;active?:boolean;paged?:boolean;twoCompanies?:boolean;wrongAdmission?:boolean;action?:Selection['action']}={}) {
  await mockWorkspace(page);let current=saved(options.action);let denied=false,headsChanged=false,user='test.pm@example.invalid';let startCount=0,stopCount=0;
  const requests:{method:string;body:Record<string,unknown>;key?:string}[]=[];const reads:{method:string;company:string|null;record_id:string|null}[]=[];const admissions=new Map<string,Run>();const stops=new Map<string,Record<string,unknown>>();
  if(options.active)current.run={...current.run,status:'queued',completed_at:null,result:null,result_digest:null};
  const send=(route:Route,data:unknown)=>route.fulfill({contentType:'application/json',body:JSON.stringify({message:{schema:'cipher.api.v1',data}})});
  const forbidden=(route:Route)=>route.fulfill({status:403,contentType:'application/json',body:JSON.stringify({message:{schema:'cipher.api.v1',error:{code:'capability_denied',message:'Original source access denied.'}}})});
  const pursuit={id:ids.pursuit,company,author_person:'TEST-PERSON-001',revision_number:1,opportunity:'Fixture Opportunity',native_version:'1',party_type:'Customer',party_id:'Fixture Customer',title:'Selected waterworks pursuit',fields:{title:'Selected waterworks pursuit'},stage:'identified'};
  await page.route('**/api/method/**',async route=>{
    const request=route.request();const url=new URL(request.url());const full=url.pathname.split('/').at(-1)!;const method=full.split('.').at(-1)!;const scope=url.searchParams.get('company');
    if(full==='cipher_aec.api.v1.session')return send(route,{authenticated:true,user,person:{id:'TEST-PERSON-001',display_name:'Alex Morgan'},companies:[{id:company,name:'Company A'},...(options.twoCompanies?[{id:'COMPANY-B',name:'Company B'}]:[])],company_scopes:[{company,capabilities:['company.read','commercial.read','estimate.read','document.read','ricky.run']},...(options.twoCompanies?[{company:'COMPANY-B',capabilities:['company.read','commercial.read','estimate.read','document.read','ricky.run']}]:[])],capabilities:[],csrf_token:'test-csrf',site_mode:'synthetic'});
    if(full.startsWith('cipher_aec.ricky.api.'))throw new Error('Company suggestions must not dispatch Project/model routes.');
    if(request.method()==='POST'){
      if(!full.startsWith('cipher_aec.ricky.company_proposal_api.')||!['start_proposal','cancel_run'].includes(method))throw new Error('Unapproved suggestion mutation '+full);
      const body=request.postDataJSON();requests.push({method,body,key:request.headers()['idempotency-key']});expect(request.headers()['idempotency-key']).toBe(body.operation_id);expect(body).not.toHaveProperty('project');expect(body.company).toBe(company);
      if(method==='start_proposal'){
        startCount++;if(denied)return forbidden(route);
        const previous=admissions.get(body.operation_id);if(previous)return send(route,{...previous,operation:{id:body.operation_id,status:'succeeded',replayed:true}});
        current=saved(body.request.action,body.request);const admission={...current.run,status:'queued',completed_at:null,result:null,result_digest:null,error:null} as Run;admissions.set(body.operation_id,admission);
        if(options.lostStart&&startCount===1)return route.abort('failed');
        return send(route,{...(options.wrongAdmission?current.run:admission),operation:{id:body.operation_id,status:'succeeded',replayed:false}});
      }
      stopCount++;const previous=stops.get(body.operation_id);if(previous)return send(route,{...previous,operation:{id:body.operation_id,status:'succeeded',replayed:true}});
      if(!['waiting-for-review','failed','cancelled'].includes(current.run.status))current.run={...current.run,status:'cancelled',cancel_requested:true,completed_at:'2020-10-16T00:00:02Z',result:null,result_digest:null};
      const stop={id:current.run.id,company,scope_type:'Company',project:null,request_kind:'deterministic-proposal-v1',status:current.run.status,cancel_requested:current.run.cancel_requested};stops.set(body.operation_id,stop);
      if(options.lostStop&&stopCount===1)return route.abort('failed');return send(route,{...stop,operation:{id:body.operation_id,status:'succeeded',replayed:false}});
    }
    reads.push({method:full,company:scope,record_id:url.searchParams.get('record_id')});
    if(full.startsWith('cipher_aec.ricky.company_proposal_api.')){if(denied)return forbidden(route);if(method==='get_run')return send(route,current.run);if(method==='run_events')return send(route,options.active?{items:[]}:current.events);if(method==='get_proposal')return send(route,current.proposal);throw new Error('Unknown proposal route');}
    if(full==='cipher_aec.commercial.api.pursuits')return send(route,{items:scope==='COMPANY-B'?[]:[pursuit],next_cursor:null,limit:30,count_mode:'exact',total:scope==='COMPANY-B'?0:1});
    if(full==='cipher_aec.commercial.api.pursuit')return send(route,pursuit);
    if(full==='cipher_aec.commercial.api.proposals')return send(route,{items:options.paged&&!url.searchParams.get('cursor')?[]:[{id:ids.commercial,company,pursuit:ids.pursuit,title:'Working commercial draft',current_revision:headsChanged?ids.successor:ids.commercialRevision,revision_number:headsChanged?2:1}],next_cursor:options.paged&&!url.searchParams.get('cursor')?'next-proposal-page':null,limit:30,count_mode:'exact',total:1});
    if(full==='cipher_aec.commercial.api.proposal')return send(route,{id:ids.commercial,company,pursuit:ids.pursuit,title:'Working commercial draft',current_revision:headsChanged?ids.successor:ids.commercialRevision,revision:{id:headsChanged?ids.successor:ids.commercialRevision,company,proposal:ids.commercial,status:'draft',revision_number:headsChanged?2:1}});
    if(full.startsWith('cipher_aec.estimating.company_api.')){
      const kind=url.searchParams.get('kind'),recordId=url.searchParams.get('record_id');
      if(method==='list_records')return send(route,{items:[{id:ids.estimate,company,scope_type:'Company',project:null,pursuit_id:ids.pursuit,title:'Working drainage estimate',current_revision:headsChanged?ids.successor:ids.estimateRevision}],next_cursor:null,limit:50,count_mode:'exact',total:1});
      if(kind==='estimate')return send(route,{id:ids.estimate,company,scope_type:'Company',project:null,pursuit_id:ids.pursuit,title:'Working drainage estimate',current_revision:headsChanged?ids.successor:ids.estimateRevision});
      if(kind==='revision')return send(route,{id:recordId,company,scope_type:'Company',project:null,estimate:ids.estimate,calculation_snapshot:ids.snapshot,line_record_ids:[ids.line],revision_number:recordId===ids.successor?2:1});
      if(kind==='snapshot')return send(route,{id:ids.snapshot,company,scope_type:'Company',project:null,estimate:ids.estimate,subject_id:ids.estimateRevision,inputs:{unit_manifest:unitManifest}});
      if(kind==='line')return send(route,line);throw new Error('Unexpected estimate helper route');
    }
    if(full.startsWith('cipher_aec.documents.company_api.')){
      if(denied)return forbidden(route);
      if(method==='search_documents')return send(route,{items:[citation]});if(method==='get_citation')return send(route,citation);
      if(method==='get_document')return send(route,{document:{id:citation.document_id,title:citation.document_title,current_revision:citation.revision_id,company,scope_type:'Company',project:null,mime_type:'text/plain',filename:'source.txt',page_count:1},revisions:[{id:citation.revision_id,revision_number:1,filename:'source.txt',company,scope_type:'Company',project:null}]});
      if(method==='preview_revision')return send(route,{document_id:citation.document_id,revision_id:citation.revision_id,company,scope_type:'Company',project:null,page:1,page_count:1,text:citation.excerpt,content_type:'text/plain',citation});
    }
    if(full==='cipher_aec.takeoff.company_api.list_records')return send(route,{items:[],next_cursor:null,limit:20,count_mode:'none',total:null});
    return route.fallback();
  });
  if(options.pointer)await page.addInitScript(({key,value})=>sessionStorage.setItem(key,value),{key:suggestionPointerKey(user,'TEST-PERSON-001',company),value:current.run.id});
  return {requests,reads,effects:()=>admissions.size,setDenied:(value:boolean)=>{denied=value;},advanceHeads:()=>{headsChanged=true;},alias:()=>{user='same.person.alias@example.invalid';},mutateRun:(change:Partial<Run>)=>{current.run={...current.run,...change};},mutateProposal:(change:Partial<Proposal>)=>{current.proposal={...current.proposal,...change} as Proposal;},current:()=>current};
}

export async function selectOption(page:Page,label:string,text:string){await page.getByRole('combobox',{name:label,exact:true}).click();await page.getByRole('option',{name:text,exact:true}).click();}
export async function openSuggestions(page:Page){await page.goto('/commercial/pursuits');if((page.viewportSize()?.width||1440)<600){await page.getByRole('button',{name:'Toggle navigation',exact:true}).click();await page.getByRole('treeitem',{name:'Ricky',exact:true}).click();}else await page.getByRole('button',{name:'Toggle Ricky assistant'}).click();await page.getByRole('button',{name:'Saved suggestions',exact:true}).click();await expect(page.getByRole('complementary',{name:'Company saved suggestions'})).toBeVisible();}
export async function evidence(page:Page){await page.getByRole('textbox',{name:'Find suggestion evidence',exact:true}).fill('Original');await page.getByRole('button',{name:'Find suggestion evidence',exact:true}).click();const checkbox=page.getByRole('checkbox',{name:'Original source specification · Rev. 1 · Page 1',exact:true});await checkbox.click();await expect(checkbox).toBeChecked();}
export async function scopeInputs(page:Page,options:{paged?:boolean}={}){await selectOption(page,'Suggestion pursuit','Selected waterworks pursuit');if(options.paged)await page.getByRole('button',{name:'More working records',exact:true}).click();await selectOption(page,'Suggestion working record','Working commercial draft');await page.getByRole('textbox',{name:'Scope text 1',exact:true}).fill('Review the drainage work from the original source.');await page.getByRole('textbox',{name:'Suggestion unverified statements',exact:true}).fill('Verify access conditions.');await evidence(page);}
