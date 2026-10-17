import { expect, test } from '@playwright/test';
import { companyRunPointerKey, matchesCompanyRun, matchesCompanyStop, matchesCompanyEvents, sameSelectedValue, matchesSelectedResult } from '../src/api/company-ricky-validation';
import type { CompanyRickyRunResponse, CompanyRickyStopResponse, CompanyRickyRunEventsResponse, CompanyRickySelectedRead } from '../src/api/company-ricky.generated';
const id = '11111111-1111-4111-8111-111111111111';
const run: CompanyRickyRunResponse = {id,company:'Company A',scope_type:'Company',project:null,request_kind:'deterministic-read-v1',status:'queued',cancel_requested:false,created_at:'2026-10-16T00:00:00Z',completed_at:null,action:'aec.pursuit.lookup',result:null,result_digest:null,error:null,standing:{mode:'deterministic-read-v1',model_invoked:false,live_model_qualified:false},result_basis:'original-tool-observation-v1',selection:{schema:'cipher.ricky.company.read-request.v1',pursuit_id:id,action:'aec.pursuit.lookup',arguments:{},sources:[],measurement_ids:[]},selection_digest:'a'.repeat(64)};
test('Company run gate refuses changed Company, run, scope and model standing',()=>{
 expect(matchesCompanyRun(run,'Company A',id)).toBe(true);
 for(const changed of [{company:'Company B'},{id:'other'},{scope_type:'Project'},{project:'PROJ-1'},{standing:{...run.standing,model_invoked:true}},{result_basis:'current-head'}]) expect(matchesCompanyRun({...run,...changed} as CompanyRickyRunResponse,'Company A',id)).toBe(false);
});
test('source-free Stop has its own exact scope and terminal identity gate',()=>{
 const stop:CompanyRickyStopResponse={id,company:'Company A',scope_type:'Company',project:null,request_kind:'deterministic-read-v1',status:'cancelled',cancel_requested:true,operation:{id,status:'succeeded',replayed:false}};
 expect(matchesCompanyStop(stop,'Company A',id)).toBe(true);expect(matchesCompanyRun(stop as unknown as CompanyRickyRunResponse,'Company A',id)).toBe(false);
 expect(matchesCompanyStop(stop,'Company B',id)).toBe(false);expect(matchesCompanyStop({...stop,status:'queued'} as unknown as CompanyRickyStopResponse,'Company A',id)).toBe(false);
});
test('browser pointers isolate exact native User, Person and Company without delimiter ambiguity',()=>{
 const keys=[companyRunPointerKey('userA','personA','A'),companyRunPointerKey('aliasA','personA','A'),companyRunPointerKey('userA','personB','A'),companyRunPointerKey('userA','personA','B'),companyRunPointerKey('a.b','c','d'),companyRunPointerKey('a','b.c','d')];expect(new Set(keys).size).toBe(keys.length);
});
test('event inventory rejects wrong run, wrong action, duplicates and malformed rows without throwing',()=>{
 const row={id,run_id:id,status:'succeeded' as const,tool_name:run.action,created_at:run.created_at,completed_at:run.created_at,error:null};
 expect(matchesCompanyEvents({items:[row]},id,run.action)).toBe(true);
 for(const items of [[{...row,run_id:'other'}],[{...row,tool_name:'aec.estimate.compare'}],[row,row],[null]])expect(matchesCompanyEvents({items} as unknown as CompanyRickyRunEventsResponse,id,run.action)).toBe(false);
});

test('selected payload equality preserves primitive types, array order and exact closed field inventory',()=>{
 expect(sameSelectedValue({a:1,b:['x']},{b:['x'],a:1})).toBe(true);
 expect(sameSelectedValue({a:true},{a:1})).toBe(false);expect(sameSelectedValue(['a','b'],['b','a'])).toBe(false);expect(sameSelectedValue({a:1},{a:1,extra:2})).toBe(false);
});
test('result linkage binds the original selected pursuit and rejects successful null output',()=>{
 const selection:CompanyRickySelectedRead={schema:'cipher.ricky.company.read-request.v1',pursuit_id:id,action:'aec.pursuit.lookup',arguments:{},sources:[],measurement_ids:[]};
 const completed={...run,status:'succeeded' as const,completed_at:'2026-10-16T00:00:01Z',result_digest:'a'.repeat(64),result:{scope_type:'Company' as const,company:run.company,pursuit_id:id,record_digest:'b'.repeat(64),revision_number:1,title:'Original pursuit'}};
 expect(matchesSelectedResult(completed,selection)).toBe(true);expect(matchesSelectedResult({...completed,result:{...completed.result,pursuit_id:'other'}},selection)).toBe(false);expect(matchesSelectedResult({...completed,result:null},selection)).toBe(false);
});

test('Stop rejects source-bearing extras and a terminal status with a contradictory cancellation flag',()=>{
 const stop:CompanyRickyStopResponse={id,company:'Company A',scope_type:'Company',project:null,request_kind:'deterministic-read-v1',status:'cancelled',cancel_requested:true,operation:{id,status:'succeeded',replayed:false}};
 expect(matchesCompanyStop({...stop,result:{secret:'source'}} as CompanyRickyStopResponse,'Company A',id)).toBe(false);expect(matchesCompanyStop({...stop,cancel_requested:false},'Company A',id)).toBe(false);expect(matchesCompanyStop({...stop,status:'succeeded'},'Company A',id)).toBe(false);
});
test('queued or failed partial result and inconsistent completion cannot become a positive observation',()=>{
 const result={scope_type:'Company' as const,company:run.company,pursuit_id:id,record_digest:'b'.repeat(64),revision_number:1,title:'Original pursuit'};
 expect(matchesSelectedResult({...run,result,result_digest:'a'.repeat(64)},run.selection)).toBe(false);expect(matchesSelectedResult({...run,status:'failed',result,result_digest:'a'.repeat(64),completed_at:'2026-10-16T00:00:01Z'},run.selection)).toBe(false);expect(matchesSelectedResult({...run,status:'succeeded',result,result_digest:'a'.repeat(64)},run.selection)).toBe(false);
});
