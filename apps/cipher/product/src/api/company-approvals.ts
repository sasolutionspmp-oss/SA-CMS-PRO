import { rpc } from './client';
import type { AwardExecutionExpectation } from '../award-governance';
import type { AwPlan } from './awards.generated';
export type ApprovalIdentity = { action: string; subject_id: string; subject_type: string; source_version: string; manifest_hash: string; award?: AwardExecutionExpectation };
import type { CompanyApprovalPacket, CompanyApprovalList, CompanyApprovalCommandResponse, CompanyApprovalExecutionResponse } from './contracts.generated';
const prefix = 'cipher_aec.api.company_approvals.';
export const companyApprovals = {
  list: (company: string, cursor?: string, signal?: AbortSignal) => rpc<CompanyApprovalList>(prefix + 'list_packets', { company, cursor, limit: 10, count_mode: 'none' }, false, signal),
  read: (company: string, packet_id: string, signal?: AbortSignal) => rpc<CompanyApprovalPacket>(prefix + 'read_packet', { company, packet_id }, false, signal),
  requestDistribution: (input: { company: string; subject_id: string; expected_version: string; operation_id?: string }) => rpc<CompanyApprovalCommandResponse>(prefix + 'request_action', { ...input, action: 'proposal.distribute.v1' }, true),
  requestIssue: (input: { company: string; subject_id: string; expected_version: string; operation_id?: string }) => rpc<CompanyApprovalCommandResponse>(prefix + 'request_action', { ...input, action: 'proposal.issue.v1' }, true),
  requestAcceptance: (input: { company: string; subject_id: string; expected_version: string; operation_id?: string }) => rpc<CompanyApprovalCommandResponse>(prefix + 'request_action', { ...input, action: 'estimate.accept.v1' }, true),
  requestAward: (input: { company: string; subject_id: string; expected_version: string; operation_id?: string; expected_plan: AwPlan }) => { const { expected_plan: _expected, ...parameters } = input; return rpc<CompanyApprovalCommandResponse>(prefix + 'request_action', { ...parameters, action: 'award.project.create.v1' }, true); },
  act: (input: { company: string; packet_id: string; manifest_hash: string; action: 'Grant' | 'Reject' | 'execute' | 'withdraw'; reason: string; operation_id?: string; expected_packet?: ApprovalIdentity }) => { const { action, expected_packet: _expected, ...parameters } = input; return rpc<CompanyApprovalCommandResponse | CompanyApprovalExecutionResponse>(prefix + (action === 'execute' ? 'execute_packet' : action === 'withdraw' ? 'withdraw_packet' : 'decide_packet'), { ...parameters, ...(action === 'Grant' || action === 'Reject' ? { decision: action } : {}), ...(action === 'execute' ? { reason: undefined } : {}) }, true); },
};
