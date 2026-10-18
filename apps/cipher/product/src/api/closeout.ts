import schema from '../../../platform/apps/cipher_aec/cipher_aec/closeout/schemas/api-v1.schema.json' with { type: 'json' };
import { ApiError, rpc } from './client';
import { engineeringDigest } from './engineering';
import { sameValue, schemaShape } from './schema-validation';
import type * as C from './closeout.generated';
import type { Actor, Scope } from '../closeout-model';
export type Kind = 'package' | 'package_revision' | 'commissioning_requirement' | 'requirement' | 'test_result' | 'asset_handover' | 'decision' | 'turnover';
type Requests = { create_package: C.CreatePackageRequest; revise_package: C.RevisePackageRequest; record_result: C.RecordResultRequest; accept_result: C.AcceptResultRequest; assemble_turnover: C.AssembleTurnoverRequest; accept_turnover: C.AcceptTurnoverRequest };
export type Basis = {header:C.CloseoutRecordResult;revision:C.CloseoutRecordResult};
export type Command = { [K in keyof Requests]: { kind: K; payload: Omit<Requests[K], 'operation_id'> } & (K extends 'create_package'?{}:{basis:Basis}) }[keyof Requests];
export type Reply = C.CloseoutCommandResult;
export const invalidCloseout = () => new ApiError('The closeout reply could not be matched to the selected Company, project and exact revision.', 'INVALID_CONTRACT', 200);
const prefix = 'cipher_aec.closeout.api.';
const recordDefs: Record<Kind, string> = { package: 'CloseoutHeader', package_revision: 'CloseoutPackageRevision', commissioning_requirement: 'CloseoutRequirement', requirement: 'CloseoutRequirement', test_result: 'CloseoutResult', asset_handover: 'CloseoutResult', decision: 'CloseoutDecision', turnover: 'CloseoutTurnover' };
export const closeoutShape = (name: string, value: unknown) => schemaShape(schema, name, value);
const scoped = (record: { company: string; project: string; scope_type: string }, scope: Scope) => record.company === scope.company && record.project === scope.project && record.scope_type === 'Project';
export async function validateRecord(value: C.CloseoutRecordResult, scope: Scope, kind: Kind, id?: string, parent?: string) {
  if (!closeoutShape('CloseoutRecordResult', value) || !closeoutShape(recordDefs[kind], value.record) || !scoped(value.record, scope) || id && value.record.id !== id || parent && (!('parent_id' in value.record) || value.record.parent_id !== parent) || await engineeringDigest(value.record) !== value.record_digest) throw invalidCloseout();
  if ((kind === 'commissioning_requirement' || kind === 'requirement') && 'category' in value.record && (kind === 'commissioning_requirement') !== (value.record.category === 'commissioning')) throw invalidCloseout();
  return value;
}
const requestNames: Record<keyof Requests, string> = { create_package: 'CreatePackageRequest', revise_package: 'RevisePackageRequest', record_result: 'RecordResultRequest', accept_result: 'AcceptResultRequest', assemble_turnover: 'AssembleTurnoverRequest', accept_turnover: 'AcceptTurnoverRequest' };
export const closeout = {
  async get(scope: Scope, kind: Kind, id: string, signal?: AbortSignal) { return validateRecord(await rpc<C.CloseoutRecordResult>(prefix + 'get_record', { ...scope, kind, record_id: id }, false, signal), scope, kind, id); },
  async list(scope: Scope, kind: Kind, parent_id?: string, cursor?: string, signal?: AbortSignal) {
    const page = await rpc<C.CloseoutListResult>(prefix + 'list_records', { ...scope, kind, parent_id, cursor, limit: 25, count_mode: 'none' }, false, signal);
    if (!closeoutShape('CloseoutListResult', page) || page.limit !== 25 || page.count_mode !== 'none' || page.items.length > 25 || page.total !== null || cursor && cursor === page.next_cursor || new Set(page.items.map(row => row.record.id)).size !== page.items.length) throw invalidCloseout();
    await Promise.all(page.items.map(row => validateRecord(row, scope, kind, undefined, parent_id))); return page;
  },
  async send(command: Command & { operation_id: string }, actor: Actor & Scope): Promise<Reply> {
    const input = { ...command.payload, operation_id: command.operation_id };
    if (!sameValue({ company: input.company, project: input.project }, { company: actor.company, project: actor.project }) || !closeoutShape(requestNames[command.kind], input)) throw new ApiError('Complete the closeout fields, exact evidence and links before saving.', 'closeout_input', 422);
    let original:C.CloseoutHeader|undefined,originalRevision:C.CloseoutPackageRevision|undefined;
    if(command.kind!=='create_package'){
      await validateRecord(command.basis.header,actor,'package',command.payload.package_id);
      original=command.basis.header.record as C.CloseoutHeader;
      await validateRecord(command.basis.revision,actor,'package_revision',original.current_revision!);
      originalRevision=command.basis.revision.record as C.CloseoutPackageRevision;
      if(command.payload.expected_version!==command.basis.header.record_digest||originalRevision.parent_id!==original.id)throw invalidCloseout();
    }
    const reply = await rpc<Reply>(prefix + command.kind, input, true);
    if (!closeoutShape('CloseoutCommandResult', reply) || reply.operation.id!==command.operation_id || !scoped(reply.package, actor) || 'package_id' in input && reply.package.id !== input.package_id) throw invalidCloseout();
    const fields:Record<keyof Requests,string[]>={create_package:['package_revision','requirements'],revise_package:['package_revision','requirements'],record_result:['result'],accept_result:['result','decision'],assemble_turnover:['turnover'],accept_turnover:['turnover','decision']};
    const expectedKeys=['package','history_id','operation',...fields[command.kind]].sort();
    if(!sameValue(Object.keys(reply).sort(),expectedKeys))throw invalidCloseout();
    const authored = command.kind === 'create_package' || command.kind === 'revise_package' ? reply.package_revision : command.kind === 'record_result' ? reply.result : command.kind === 'assemble_turnover' ? reply.turnover : reply.decision;
    if (!authored || !scoped(authored, actor) || authored.parent_id !== reply.package.id || authored.author_user !== actor.user || authored.author_person !== actor.personId) throw invalidCloseout();
    if ('definition' in input && (!('definition' in authored) || !sameValue(authored.definition, input.definition))) throw invalidCloseout();
    if (command.kind === 'record_result') {
      if (!reply.result || reply.result.requirement_id !== command.payload.requirement_id || !sameValue(reply.result.evidence.map(({ revision_id, source_sha256, page, locator }) => ({ revision_id, source_sha256, page, locator })), command.payload.evidence) || !sameValue(reply.result.links, command.payload.links)) throw invalidCloseout();
    }
    if (command.kind === 'accept_result' && (!reply.decision || reply.decision.action !== 'accept_result' || reply.decision.subject_id !== command.payload.result_id || reply.decision.subject_digest !== command.payload.result_digest || reply.decision.comment !== command.payload.comment)) throw invalidCloseout();
    if (command.kind === 'accept_turnover' && (!reply.decision || reply.decision.action !== 'accept_turnover' || reply.decision.subject_id !== command.payload.turnover_id || reply.decision.subject_digest !== command.payload.turnover_digest || reply.decision.comment !== command.payload.comment)) throw invalidCloseout();
    if (command.kind === 'assemble_turnover' && reply.turnover?.comment !== command.payload.comment) throw invalidCloseout();
    if(command.kind==='create_package'||command.kind==='revise_package'){
      const revision=reply.package_revision!,requirements=reply.requirements!;
      if(reply.package.current_revision!==revision.id||reply.package.revision_number!==revision.revision_number||revision.parent_id!==reply.package.id||revision.requirements.length!==requirements.length||requirements.length!==command.payload.requirements.length)throw invalidCloseout();
      for(let i=0;i<requirements.length;i++){
        const requirement=requirements[i],ref=revision.requirements[i],source=command.payload.requirements[i];
        if(!scoped(requirement,actor)||requirement.parent_id!==reply.package.id||requirement.package_revision!==revision.id||requirement.revision_number!==revision.revision_number||requirement.author_user!==actor.user||requirement.author_person!==actor.personId||ref.id!==requirement.id||ref.record_digest!==await engineeringDigest(requirement)||(ref.kind==='commissioning_requirement')!==(source.category==='commissioning')||!sameValue(Object.fromEntries(Object.keys(source).map(key=>[key,requirement[key as keyof C.CloseoutRequirement]])),source))throw invalidCloseout();
      }
      if(command.kind==='create_package'){
        if(reply.package.author_user!==actor.user||reply.package.author_person!==actor.personId||reply.package.status!=='draft'||reply.package.revision_number!==1||reply.package.result_heads.length||reply.package.accepted_results.length||reply.package.turnover_head!==null||reply.package.accepted_turnover!==null||revision.predecessor!==null||revision.amendment_of!==null||revision.amendment_reason!=='')throw invalidCloseout();
      }else{
        if(revision.predecessor!==original!.current_revision||revision.revision_number!==original!.revision_number+1||revision.amendment_of!==original!.accepted_turnover||revision.amendment_reason!==(command.payload.amendment_reason||'')||!sameValue(reply.package,{...original,status:'draft',current_revision:revision.id,revision_number:revision.revision_number,result_heads:[],accepted_results:[],turnover_head:null}))throw invalidCloseout();
      }
    }else if(command.kind==='record_result'){
      const result=reply.result!,ref=originalRevision!.requirements.find(row=>row.id===command.payload.requirement_id),prior=original!.result_heads.find(row=>row.requirement_id===command.payload.requirement_id),kind=Object.hasOwn(result.definition,'recipient_as_recorded')?'asset_handover':'test_result';
      if(!ref||result.requirement_digest!==ref.record_digest||result.package_revision!==original!.current_revision||result.predecessor!==(prior?.result_id||null)||!sameValue(reply.package,{...original,status:'draft',result_heads:[...original!.result_heads.filter(row=>row.requirement_id!==result.requirement_id),{requirement_id:result.requirement_id,result_kind:kind,result_id:result.id}],accepted_results:original!.accepted_results.filter(row=>row.requirement_id!==result.requirement_id),turnover_head:null}))throw invalidCloseout();
    }else if(command.kind==='accept_result'){
      const result=reply.result!,decision=reply.decision!,head=original!.result_heads.find(row=>row.result_id===result.id);
      if(!head||await engineeringDigest(result)!==command.payload.result_digest||decision.subject_kind!==head.result_kind||decision.package_revision!==original!.current_revision||result.author_person===actor.personId||result.definition.outcome!=='pass'||!sameValue(reply.package,{...original,status:'draft',accepted_results:[...original!.accepted_results.filter(row=>row.requirement_id!==head.requirement_id),{...head,result_digest:command.payload.result_digest,decision_id:decision.id,decision_digest:await engineeringDigest(decision)}],turnover_head:null}))throw invalidCloseout();
    }else if(command.kind==='assemble_turnover'){
      const turnover=reply.turnover!;
      if(turnover.package_revision!==original!.current_revision||turnover.package_digest!==command.basis.revision.record_digest||!sameValue(turnover.items,original!.accepted_results)||!sameValue(reply.package,{...original,status:'assembled',turnover_head:turnover.id}))throw invalidCloseout();
    }else{
      const turnover=reply.turnover!,decision=reply.decision!;
      if(await engineeringDigest(turnover)!==command.payload.turnover_digest||decision.subject_kind!=='turnover'||decision.package_revision!==original!.current_revision||turnover.author_person===actor.personId||originalRevision!.author_person===actor.personId||!sameValue(reply.package,{...original,status:'accepted',accepted_turnover:turnover.id}))throw invalidCloseout();
    }
    return reply;
  },
};
