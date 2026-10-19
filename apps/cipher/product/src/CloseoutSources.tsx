import { useEffect, useRef, useState } from 'react';
import { Button, Input, Label, Option, Select, Title } from '@ui5/webcomponents-react';
import { ApiError } from './api/client';
import { sourceApi } from './api/sources';
import { listCloseoutLinks, verifyCloseoutLink } from './api/closeout-links';
import type * as C from './api/closeout.generated';
import type { Scope } from './closeout-model';
import { Failure, Loading, Pagination } from './components';
import { useResource } from './hooks';
type Source = C.RecordResultRequest['evidence'][number];
const linkLabels: Record<C.CloseoutLink['kind'], string> = { engineering_check: 'Engineering check', document_adoption: 'Document adoption', quality_closure: 'Quality closure' };
const denied = (error: unknown) => error instanceof ApiError && [401,403,404].includes(error.status);
export function CloseoutEvidencePicker({scope, value, onChange, locked, onDenied}: {scope: Scope; value: Source[]; onChange: (value: Source[])=>void; locked: boolean; onDenied:()=>void}) {
  const sources = useResource(`${scope.company}/${scope.project}/closeout/ordinary-sources`, async signal => {
    const page = await sourceApi({type:'Project',...scope}).list(signal);
    if (page.items.some(row => row.company !== scope.company || row.project !== scope.project || !/^[a-f0-9]{64}$/.test(row.sha256) || !Number.isSafeInteger(row.page_count) || row.page_count < 1)) throw new ApiError('The ordinary project sources could not be verified.','INVALID_CONTRACT',200);
    return page.items;
  });
  const [id,setId]=useState(''),[page,setPage]=useState('1'),[locator,setLocator]=useState('');
  useEffect(()=>{if(denied(sources.error))onDenied();},[sources.error,onDenied]);
  const document=sources.data?.find(row=>row.id===id),number=Number(page),valid=document&&Number.isSafeInteger(number)&&number>=1&&number<=document.page_count&&locator.trim();
  return <section className="closeout-form-section"><Title wrappingType="Normal" level="H3">Evidence</Title><p>Choose a project document, page and location.</p>{sources.loading?<Loading label="Loading project documents…"/>:sources.error?<Failure error={sources.error}/>:<><Label>Project document</Label><Select accessibleName="Closeout evidence document" disabled={locked} onChange={e=>{setId(e.detail.selectedOption.value||'');setPage('1');}}><Option value="" selected={!id}>Choose a document</Option>{sources.data?.map(row=><Option key={row.id} value={row.id} selected={row.id===id}>{row.title} · Rev. {row.revision_number}</Option>)}</Select></>}<Label>Page</Label><Input accessibleName="Closeout evidence page" value={page} disabled={locked} onInput={e=>setPage(e.currentTarget!.value)}/><Label required>Evidence location</Label><Input accessibleName="Closeout evidence location" value={locator} disabled={locked} onInput={e=>setLocator(e.currentTarget!.value)} placeholder="For example: test sheet 4, pump P-101"/><Button disabled={locked||!valid||value.length>=8} onClick={()=>{if(document&&valid){const row={revision_id:document.current_revision,source_sha256:document.sha256,page:number,locator:locator.trim()};if(!value.some(s=>s.revision_id===row.revision_id&&s.page===row.page&&s.locator===row.locator))onChange([...value,row]);}}}>Attach evidence</Button><ul>{value.map((row,i)=><li className="closeout-evidence-row" key={`${row.revision_id}/${row.page}/${row.locator}`}><span>{sources.data?.find(document=>document.current_revision===row.revision_id)?.title||'Attached document'} · Page {row.page} · {row.locator}</span><Button accessibleName={`Remove evidence ${i+1}`} disabled={locked} onClick={()=>onChange(value.filter((_,n)=>n!==i))}>Remove</Button></li>)}</ul></section>;
}
export function CloseoutLinks({scope, value, onChange, locked, onDenied}: {scope: Scope; value:C.CloseoutLink[];onChange:(value:C.CloseoutLink[])=>void;locked:boolean;onDenied:()=>void}) {
  return <ScopedCloseoutLinks key={JSON.stringify([scope.company,scope.project])} scope={scope} value={value} onChange={onChange} locked={locked} onDenied={onDenied}/>;
}

function ScopedCloseoutLinks(props: {scope: Scope; value:C.CloseoutLink[];onChange:(value:C.CloseoutLink[])=>void;locked:boolean;onDenied:()=>void}) {
  const {scope, value, locked} = props;
  const [kind,setKind]=useState<C.CloseoutLink['kind']>('engineering_check'),[id,setId]=useState(''),[cursor,setCursor]=useState<string>(),[prior,setPrior]=useState<(string|undefined)[]>([]);
  const [error,setError]=useState<ApiError>(),[busy,setBusy]=useState(false);
  const key=JSON.stringify([scope.company,scope.project,'closeout/links',kind,cursor||null]);
  const current=useRef({key,props}); current.current={key,props};
  const mounted=useRef(true),verification=useRef<AbortController|undefined>(undefined);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;verification.current?.abort();};},[]);
  const choices=useResource(key,signal=>listCloseoutLinks(scope,kind,cursor,signal));
  const selected=choices.data?.items.find(choice=>choice.link.id===id);
  const verify=async()=>{
    if(locked||busy||choices.loading||choices.error||!selected||value.length>=12)return;
    const original=key,choice=selected,controller=new AbortController();
    verification.current=controller;setBusy(true);setError(undefined);
    try {
      const ref=await verifyCloseoutLink(scope,choice,controller.signal);
      if(!mounted.current||controller.signal.aborted||current.current.key!==original||current.current.props.locked)return;
      const latest=current.current.props;
      if(latest.value.length<12&&!latest.value.some(link=>link.kind===ref.kind&&link.id===ref.id)){
        latest.onChange([...latest.value,ref]);
      }
      setId('');
    }catch(failure){
      if(!mounted.current||controller.signal.aborted||current.current.key!==original)return;
      if(denied(failure))current.current.props.onDenied();
      setError(failure instanceof ApiError?failure:new ApiError('The supporting record could not be verified.','INVALID_CONTRACT',200));
    }finally{if(mounted.current&&current.current.key===original)setBusy(false);}
  };
  const changePage=(next:string|undefined)=>{setId('');setError(undefined);setCursor(next);};
  return <section className="closeout-form-section">
    <Title wrappingType="Normal" level="H3">Related records</Title><p>Choose a saved Engineering, Document Control or Quality record.</p>
    <Label>Record type</Label><Select accessibleName="Closeout supporting record type" disabled={locked||busy} onChange={e=>{setKind(e.detail.selectedOption.value as typeof kind);setId('');setCursor(undefined);setPrior([]);setError(undefined);}}>{Object.entries(linkLabels).map(([key,label])=><Option key={key} value={key} selected={key===kind}>{label}</Option>)}</Select>
    {choices.loading?<Loading label="Loading related records…"/>:choices.error?<Failure error={choices.error}/>:<>
      <Label>Record</Label><Select accessibleName="Closeout supporting record" disabled={locked||busy||!choices.data?.items.length} onChange={e=>{setId(e.detail.selectedOption.value||'');setError(undefined);}}><Option value="" selected={!id}>Choose a record</Option>{choices.data?.items.map(choice=><Option key={choice.link.id} value={choice.link.id} selected={choice.link.id===id}>{choice.label}</Option>)}</Select>
      {!choices.data?.items.length&&<p>No permitted records on this page.</p>}
      <Pagination page={prior.length+1} previous={!locked&&!busy&&Boolean(prior.length)} next={locked||busy?undefined:choices.data?.next_cursor||undefined} onNext={()=>{if(choices.data?.next_cursor){setPrior([...prior,cursor]);changePage(choices.data.next_cursor);}}} onPrevious={()=>{changePage(prior.at(-1));setPrior(prior.slice(0,-1));}}/>
    </>}
    <div className="closeout-actions"><Button disabled={locked||busy||choices.loading} onClick={()=>{setId('');setError(undefined);choices.refresh();}}>Refresh records</Button><Button disabled={locked||busy||choices.loading||Boolean(choices.error)||!selected||value.length>=12} onClick={()=>void verify()}>{busy?'Verifying…':'Attach record'}</Button></div>
    {error&&<Failure error={error}/>}
    <ul>{value.map((row,i)=><li className="closeout-evidence-row" key={`${row.kind}/${row.id}`}><span>{!choices.loading&&!choices.error&&row.kind===kind?choices.data?.items.find(choice=>choice.link.id===row.id&&choice.link.record_digest===row.record_digest)?.label||linkLabels[row.kind]:linkLabels[row.kind]}</span><details className="closeout-reference"><summary>Record details</summary><p>Record <code>{row.id}</code></p><p>SHA-256 <code>{row.record_digest}</code></p></details><Button disabled={locked||busy} accessibleName={`Remove supporting record ${i+1}`} onClick={()=>props.onChange(value.filter((_,n)=>n!==i))}>Remove</Button></li>)}</ul>
  </section>;
}
