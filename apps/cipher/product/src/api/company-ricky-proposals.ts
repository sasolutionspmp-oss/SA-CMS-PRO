import { rpc } from './client';
import type { CompanyRickyProposalStartRequest, CompanyRickyProposalStartResponse, CompanyRickyProposalGetRunRequest, CompanyRickyProposalRunResponse, CompanyRickyProposalEventsResponse, CompanyRickyProposalStopRequest, CompanyRickyProposalStopResponse, CompanyRickyProposalGetRequest, CompanyRickyProposalResponse } from './company-ricky-proposals.generated';

const prefix = 'cipher_aec.ricky.company_proposal_api.';
export const companySuggestions = {
  start: (input: CompanyRickyProposalStartRequest) => rpc<CompanyRickyProposalStartResponse>(prefix + 'start_proposal', { ...input }, true),
  run: (input: CompanyRickyProposalGetRunRequest, signal?: AbortSignal) => rpc<CompanyRickyProposalRunResponse>(prefix + 'get_run', { ...input }, false, signal),
  events: (input: CompanyRickyProposalGetRunRequest, signal?: AbortSignal) => rpc<CompanyRickyProposalEventsResponse>(prefix + 'run_events', { ...input }, false, signal),
  proposal: (input: CompanyRickyProposalGetRequest, signal?: AbortSignal) => rpc<CompanyRickyProposalResponse>(prefix + 'get_proposal', { ...input }, false, signal),
  stop: (input: CompanyRickyProposalStopRequest) => rpc<CompanyRickyProposalStopResponse>(prefix + 'cancel_run', { ...input }, true),
};
