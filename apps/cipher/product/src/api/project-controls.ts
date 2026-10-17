import { rpc } from './client';
import type { PcCreateMasterRequest, PcMasterCommand, PcMasterPage, PcResolvedRevision, PcReviseMasterRequest } from './project-controls.generated';

export type CostMasterKind = 'code' | 'type';
const companyPrefix = 'cipher_aec.project_controls.company_api.';
export const projectControls = {
  masters: (company: string, kind: CostMasterKind, basis_date: string, cursor?: string, signal?: AbortSignal) => rpc<PcMasterPage>(companyPrefix + 'list_masters', { company, kind, basis_date, cursor, limit: 10, count_mode: 'none' }, false, signal),
  revision: (company: string, kind: CostMasterKind, revision_id: string, basis_date: string, signal?: AbortSignal) => rpc<PcResolvedRevision>(companyPrefix + 'get_revision', { company, kind, revision_id, basis_date }, false, signal),
  create: (input: PcCreateMasterRequest) => rpc<PcMasterCommand>(companyPrefix + 'create_master', { ...input }, true),
  revise: (input: PcReviseMasterRequest) => rpc<PcMasterCommand>(companyPrefix + 'revise_master', { ...input }, true),
};
