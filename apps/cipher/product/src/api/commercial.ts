import { rpc } from './client';
import type { ComPursuit, ComPursuitList, ComProposalList, ComProposalDetail, ComRevision, ComComparison, ComPursuitCommand, ComProposalCommand, ComCreatePursuitRequest, ComUpdatePursuitRequest, ComCreateProposalRequest, ComSaveRevisionRequest, ComOutputSubject, ComPreparedOutput, ComPreparedOutputCommand, ComPrepareOutputRequest, ComIssue, ComIssueList } from './commercial.generated';

const prefix = 'cipher_aec.commercial.api.';
export const commercial = {
  pursuits: (company: string, cursor?: string, signal?: AbortSignal) => rpc<ComPursuitList>(prefix + 'pursuits', { company, cursor, limit: 30, count_mode: 'exact' }, false, signal),
  proposals: (company: string, cursor?: string, signal?: AbortSignal) => rpc<ComProposalList>(prefix + 'proposals', { company, cursor, limit: 30, count_mode: 'exact' }, false, signal),
  pursuit: (company: string, pursuit_id: string, signal?: AbortSignal) => rpc<ComPursuit>(prefix + 'pursuit', { company, pursuit_id }, false, signal),
  proposal: (company: string, proposal_id: string, signal?: AbortSignal) => rpc<ComProposalDetail>(prefix + 'proposal', { company, proposal_id }, false, signal),
  revision: (company: string, revision_id: string, signal?: AbortSignal) => rpc<ComRevision>(prefix + 'proposal_revision', { company, revision_id }, false, signal),
  compare: (company: string, proposal_id: string, left_revision: string, right_revision: string, signal?: AbortSignal) => rpc<ComComparison>(prefix + 'compare_revisions', { company, proposal_id, left_revision, right_revision }, false, signal),
  createPursuit: (input: ComCreatePursuitRequest) => rpc<ComPursuitCommand>(prefix + 'create_pursuit', { ...input }, true),
  updatePursuit: (input: ComUpdatePursuitRequest) => rpc<ComPursuitCommand>(prefix + 'update_pursuit', { ...input }, true),
  createProposal: (input: ComCreateProposalRequest) => rpc<ComProposalCommand>(prefix + 'create_proposal', { ...input }, true),
  outputSubject: (company: string, proposal_id: string, signal?: AbortSignal) => rpc<ComOutputSubject>(prefix + 'proposal_output_subject', { company, proposal_id }, false, signal),
  prepared: (company: string, revision_id: string, signal?: AbortSignal) => rpc<ComPreparedOutput>(prefix + 'prepared_output', { company, revision_id }, false, signal),
  prepare: (input: ComPrepareOutputRequest) => rpc<ComPreparedOutputCommand>(prefix + 'prepare_proposal_output', { ...input }, true),
  issues: (company: string, proposal_id: string, cursor?: string, signal?: AbortSignal) => rpc<ComIssueList>(prefix + 'issues', { company, proposal_id, cursor, limit: 30, count_mode: 'exact' }, false, signal),
  issue: (company: string, issue_id: string, signal?: AbortSignal) => rpc<ComIssue>(prefix + 'issue', { company, issue_id }, false, signal),
  saveProposal: (input: ComSaveRevisionRequest) => rpc<ComProposalCommand>(prefix + 'save_proposal_revision', { ...input }, true),
};
