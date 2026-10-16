import { rpc } from './client';
import type { AwHandoffList, AwHandoffResponse, AwPlanResponse, AwSourcePreview, AwPlanPreview, AwApprovalSubject, AwDelegationPolicyResponse, AwTeamChoices, AwPreviewPlanRequest, AwCreateHandoffRequest, AwPlanHandoffRequest, AwHandoffCommand, AwPlanCommand } from './awards.generated';
import type { AwardExpectedSource } from '../award-contract';

export type AwardSaveInput = AwPlanHandoffRequest & { expected_source: AwardExpectedSource };

const prefix = 'cipher_aec.awards.api.';
export const awards = {
  list: (company: string, cursor?: string, signal?: AbortSignal) => rpc<AwHandoffList>(prefix + 'list_handoffs', { company, cursor, limit: 10, count_mode: 'none' }, false, signal),
  handoff: (company: string, handoff_id: string, signal?: AbortSignal) => rpc<AwHandoffResponse>(prefix + 'get_handoff', { company, handoff_id }, false, signal),
  plan: (company: string, revision_id: string, signal?: AbortSignal) => rpc<AwPlanResponse>(prefix + 'get_plan', { company, revision_id }, false, signal),
  source: (company: string, issue_id: string, signal?: AbortSignal) => rpc<AwSourcePreview>(prefix + 'source_preview', { company, issue_id }, false, signal),
  subject: (company: string, revision_id: string, signal?: AbortSignal) => rpc<AwApprovalSubject>(prefix + 'approval_subject', { company, revision_id }, false, signal),
  policy: (company: string, signal?: AbortSignal) => rpc<AwDelegationPolicyResponse>(prefix + 'delegation_policy', { company }, false, signal),
  people: (company: string, query = '', cursor?: string, signal?: AbortSignal) => rpc<AwTeamChoices>(prefix + 'team_choices', { company, query, cursor, limit: 10, count_mode: 'none' }, false, signal),
  // Read-only POST: this validates a proposed definition and creates no receipt or effect.
  preview: (input: AwPreviewPlanRequest, signal?: AbortSignal) => rpc<AwPlanPreview>(prefix + 'preview_plan', { ...input }, true, signal),
  create: (input: AwCreateHandoffRequest) => rpc<AwHandoffCommand>(prefix + 'create_handoff', { ...input }, true),
  save: (input: AwardSaveInput) => { const { expected_source: _expected, ...parameters } = input; return rpc<AwPlanCommand>(prefix + 'plan_handoff', parameters, true); },
};
