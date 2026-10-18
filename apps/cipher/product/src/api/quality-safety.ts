import { ApiError, rpc } from './client';
import { engineeringDigest, type Actor, type Scope } from './engineering';
import { sameValue } from './schema-validation';
import { qualityShape } from './quality-safety-validation';
import type * as Q from './quality-safety.generated';
export { qualityShape } from './quality-safety-validation';
export type Header = Q.QsCreateRecordResponse['header'];
export type Revision = Q.QsCreateRecordResponse['revision'];
export type Decision = Q.QsTransitionResponse['decision'];
export type Definition = Q.QsCreateRecordRequest['definition'];
export type Family = Q.QsFamily;
export type Kind = Q.QsKind;
export type Category = Q.QsCreateRecordRequest['category'];
export type Basis = { header: Q.QsGetResponse; revision: Q.QsGetResponse; decision?: Q.QsGetResponse };
export type Command = { kind: 'create_record'; payload: Omit<Q.QsCreateRecordRequest, 'operation_id'> }
 | { kind: 'revise_record'; payload: Omit<Q.QsReviseRecordRequest, 'operation_id'>; basis: Basis }
 | { kind: 'transition'; payload: Omit<Q.QsTransitionRequest, 'operation_id'>; basis: Basis }
 | { kind: 'upload_evidence'; payload: Omit<Q.QsUploadEvidenceRequest, 'operation_id'> };
export type Reply = Q.QsCreateRecordResponse | Q.QsReviseRecordResponse | Q.QsTransitionResponse | Q.QsUploadEvidenceResponse;
const prefix = 'cipher_aec.quality_safety.api.';
export const childKind = (family: Family, child: 'revision' | 'decision'): Kind => (family === 'incident' ? 'incident_' + child : child) as Kind;
export const readAbility = (family: Family) => family === 'incident' ? 'safety.incident.read' : 'quality.read';
export const duty = (family: Family, action: string) => (family === 'incident' ? 'safety.incident.' : 'quality.') + action;
export const privateUploadAllowed = (caps: string[]) => ['safety.incident.read', 'safety.incident.evidence.manage', 'document.read', 'document.write', 'document.rights.manage'].every(cap => caps.includes(cap));
export const sourceInput = (source: Q.QsSourceInput | Q.QsCapturedSource): Q.QsSourceInput => ({ revision_id: source.revision_id, source_sha256: source.source_sha256, page: source.page, locator: source.locator });
export const sourceInputs = (sources: (Q.QsSourceInput | Q.QsCapturedSource)[]) => sources.map(sourceInput);
const scoped = (row: Q.QsRecord, scope: Scope) => row.scope_type === 'Project' && row.company === scope.company && row.project === scope.project;
const definitions: Record<Kind, string> = { record: 'QsOrdinaryHeader', revision: 'QsOrdinaryRevision', decision: 'QsOrdinaryDecision', incident: 'QsIncidentHeader', incident_revision: 'QsIncidentRevision', incident_decision: 'QsIncidentDecision' };
const contracts = { create_record: ['QsCreateRecordRequest','QsCreateRecordResponse'], revise_record: ['QsReviseRecordRequest','QsReviseRecordResponse'], transition: ['QsTransitionRequest','QsTransitionResponse'], upload_evidence: ['QsUploadEvidenceRequest','QsUploadEvidenceResponse'] } as const;
export const invalidQuality = () => new ApiError('The record or original request could not be verified.', 'INVALID_CONTRACT', 200);
export function definitionValid(value: Definition, category: Category): boolean {
  const name = category === 'incident' ? 'QsIncidentDefinition' : category === 'permit_record' ? 'QsPermitDefinition' : 'QsOrdinaryDefinition';
  if (!qualityShape(name, value) || new Set(value.required_closure_items.map(row => row.item_id)).size !== value.required_closure_items.length) return false;
  if ('valid_until' in value && Date.parse(value.valid_until) <= Date.parse(value.valid_from)) return false;
  if ('shared_evidence_revisions' in value && (new Set(value.shared_evidence_revisions).size !== value.shared_evidence_revisions.length || value.shared_evidence_revisions.length > 0 && !value.shared_evidence_statement.trim())) return false;
  return true;
}
export async function validateQualityRecord(value: Q.QsGetResponse, scope: Scope, kind: Kind, id?: string, parent?: string) {
  if (!qualityShape('QsGetResponse', value) || !qualityShape(definitions[kind], value.record) || !scoped(value.record, scope) || id && value.record.id !== id || parent && (!('parent_id' in value.record) || value.record.parent_id !== parent) || await engineeringDigest(value.record) !== value.record_digest) throw invalidQuality();
  if ('definition' in value.record && !definitionValid(value.record.definition, value.record.category)) throw invalidQuality();
  return value;
}
export function allowedActions(header: Header, revision: Revision, previous: Decision | undefined, actor: Actor, caps: string[]): Q.QsTransitionRequest['action'][] {
  const family: Family = header.category === 'incident' ? 'incident' : 'record';
  if (header.current_revision !== revision.id) return [];
  const actions: Q.QsTransitionRequest['action'][] = header.status === 'draft' ? ['submit'] : header.status === 'submitted' ? ['check','return'] : header.status === 'checked' ? ['close','return'] : [];
  return actions.filter(action => caps.includes(duty(family, action === 'submit' ? 'write' : action === 'close' ? 'close' : 'check')) && (action === 'submit' || actor.personId !== revision.author_person) && (action !== 'close' || previous?.action === 'check' && previous.source_revision === revision.id && actor.personId !== previous.author_person));
}
export async function validateQualityReply(command: Command & { operation_id: string }, value: Reply, actor: Actor): Promise<Reply> {
  const input = command.payload;
  if (!qualityShape(contracts[command.kind][1], value) || value.operation.id !== command.operation_id || value.operation.status !== 'succeeded') throw invalidQuality();
  if (command.kind === 'upload_evidence') {
    if (!('registration' in value)) throw invalidQuality();
    const r = value.registration, p = command.payload, doc = value.document, rev = value.revision;
    if (value.family !== 'incident' || value.history_id !== null || r.company !== p.company || r.project !== p.project || r.author_user !== actor.user || r.author_person !== actor.personId || r.document_id !== doc.id || doc.company !== p.company || doc.project !== p.project || doc.current_revision !== rev.id || doc.sha256 !== p.sha256 || rev.sha256 !== p.sha256 || doc.byte_length !== p.byte_length || rev.byte_length !== p.byte_length || doc.filename !== p.filename || rev.filename !== p.filename || doc.title !== p.title || r.rights_basis !== p.rights_basis || !sameValue(sourceInputs(r.permission_evidence), p.permission_evidence)) throw invalidQuality();
    return value;
  }
  if (!('header' in value) || !('family' in input) || value.family !== input.family || !scoped(value.header, input) || !scoped(value.revision, input)) throw invalidQuality();
  const h = value.header, r = value.revision, family = input.family;
  if (!qualityShape(definitions[family], h) || !qualityShape(definitions[childKind(family,'revision')], r) || h.current_revision !== r.id || h.revision_number !== r.revision_number || r.parent_id !== h.id || r.category !== h.category || !definitionValid(r.definition, r.category) || family === 'incident' && value.history_id !== null) throw invalidQuality();
  if (command.kind === 'transition') {
    if (!('decision' in value)) throw invalidQuality();
    const p = command.payload, old = command.basis.header.record as Header, revision = command.basis.revision.record as Revision, previous = command.basis.decision?.record as Decision | undefined, d = value.decision;
    const target = { submit:'submitted', check:'checked', return:'returned', close:'closed' }[p.action];
    if (old.id !== p.record_id || p.expected_version !== command.basis.header.record_digest || !sameValue(r, revision) || d.author_user !== actor.user || d.author_person !== actor.personId || !scoped(d, p) || d.parent_id !== old.id || d.source_revision !== revision.id || d.source_digest !== command.basis.revision.record_digest || d.category !== old.category || d.predecessor !== old.last_decision || d.action !== p.action || d.from_status !== old.status || d.to_status !== target || d.comment !== p.comment || !sameValue(sourceInputs(d.evidence), p.evidence) || !sameValue(d.closure.map(row=>({...row,evidence:sourceInputs(row.evidence)})),p.closure)) throw invalidQuality();
    if (p.action !== 'submit' && actor.personId === revision.author_person) throw invalidQuality();
    if (p.action === 'close' && (!previous || previous.id !== old.last_decision || previous.action !== 'check' || previous.source_revision !== revision.id || d.checked_by_person !== previous.author_person || actor.personId === previous.author_person || !sameValue([...d.closure.map(row=>row.item_id)].sort(),[...revision.definition.required_closure_items.map(row=>row.item_id)].sort()))) throw invalidQuality();
    if (!sameValue(h,{...old,status:target,last_decision:d.id,closed_revision:p.action==='close'?revision.id:old.closed_revision})) throw invalidQuality();
  } else {
    const p = command.payload;
    if (r.author_user !== actor.user || r.author_person !== actor.personId || !sameValue(r.definition,p.definition) || !sameValue(sourceInputs(r.evidence),p.evidence)) throw invalidQuality();
    if (command.kind === 'create_record') {
      if (h.author_user !== actor.user || h.author_person !== actor.personId || h.category !== command.payload.category || h.status !== 'draft' || h.revision_number !== 1 || h.last_decision !== null || h.closed_revision !== null || r.predecessor !== null || r.prior_decision !== null || r.amendment_of !== null || r.amendment_reason !== '') throw invalidQuality();
    } else {
      const old=command.basis.header.record as Header,p=command.payload;
      if (p.record_id!==old.id||p.expected_version!==command.basis.header.record_digest||!sameValue(h,{...old,current_revision:r.id,revision_number:old.revision_number+1,last_decision:null,status:'draft'})||r.predecessor!==old.current_revision||r.prior_decision!==old.last_decision||r.amendment_of!==old.closed_revision||r.amendment_reason!==(p.amendment_reason||''))throw invalidQuality();
    }
  }
  return value;
}
export const quality = {
  async get(scope: Scope, kind: Kind, id: string, signal?: AbortSignal) { return validateQualityRecord(await rpc<Q.QsGetResponse>(prefix+'get_record',{...scope,kind,record_id:id},false,signal),scope,kind,id); },
  async list(scope: Scope, kind: Kind, parent_id?: string, cursor?: string, signal?: AbortSignal) {
    const page=await rpc<Q.QsListResponse>(prefix+'list_records',{...scope,kind,parent_id,cursor,limit:25,count_mode:'none'},false,signal);
    if(!qualityShape('QsListResponse',page)||page.limit!==25||page.total!==null||page.count_mode!=='none'||page.items.length>25||cursor&&page.next_cursor===cursor||new Set(page.items.map(row=>row.record.id)).size!==page.items.length)throw invalidQuality();
    await Promise.all(page.items.map(row=>validateQualityRecord(row,scope,kind,undefined,parent_id)));return page;
  },
  async send(command: Command & { operation_id:string }, actor: Actor): Promise<Reply> {
    const input={...command.payload,operation_id:command.operation_id};
    if(!qualityShape(contracts[command.kind][0],input))throw new ApiError('Complete the required fields and evidence before saving.','invalid_quality_input',422);
    if(command.kind==='upload_evidence'){
      const p=command.payload,bytes=Uint8Array.from(atob(p.content_base64),char=>char.charCodeAt(0));
      const actual=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');
      if(bytes.length!==p.byte_length||actual!==p.sha256)throw new ApiError('The selected file changed. Select it again.','invalid_quality_input',422);
    }
    return validateQualityReply(command,await rpc<Reply>(prefix+command.kind,input,true),actor);
  },
};
