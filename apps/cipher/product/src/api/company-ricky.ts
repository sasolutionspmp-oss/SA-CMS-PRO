import { rpc } from './client';
import type { CompanyRickyStartReadRequest, CompanyRickyStartReadResponse, CompanyRickyGetRunRequest, CompanyRickyRunResponse, CompanyRickyRunEventsResponse, CompanyRickyCancelRunRequest, CompanyRickyStopResponse } from './company-ricky.generated';
const prefix = 'cipher_aec.ricky.company_api.';
// Company authority is explicit. No Project/model/proposal endpoint is dispatched here.
export const companyRicky = {
  start: (input: CompanyRickyStartReadRequest) => rpc<CompanyRickyStartReadResponse>(prefix + 'start_read', { ...input }, true),
  run: (input: CompanyRickyGetRunRequest, signal?: AbortSignal) => rpc<CompanyRickyRunResponse>(prefix + 'get_run', { ...input }, false, signal),
  events: (input: CompanyRickyGetRunRequest, signal?: AbortSignal) => rpc<CompanyRickyRunEventsResponse>(prefix + 'run_events', { ...input }, false, signal),
  stop: (input: CompanyRickyCancelRunRequest) => rpc<CompanyRickyStopResponse>(prefix + 'cancel_run', { ...input }, true),
};
