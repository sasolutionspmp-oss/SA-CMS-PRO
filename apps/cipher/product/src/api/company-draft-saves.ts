import { rpc } from './client';
import type { CompanyDraftSaveRequest, CompanyDraftSaveResponse, CompanyDraftSaveSubject } from './company-draft-saves.generated';

const prefix = 'cipher_aec.ricky.company_draft_save_api.';
export const companyDraftSaves = {
  subject: (company: string, proposal_id: string, signal?: AbortSignal) => rpc<CompanyDraftSaveSubject>(prefix + 'draft_save_subject', { company, proposal_id }, false, signal),
  save: (input: CompanyDraftSaveRequest) => rpc<CompanyDraftSaveResponse>(prefix + 'save_draft', { ...input }, true),
};
