import { rpc, ApiError } from './client';
import type { CompanyEstEstimateRecord, CompanyEstRevisionRecord, CompanyEstSnapshotRecord, CompanyEstRateRecord, CompanyEstAssemblyRecord, CompanyEstConversionRecord, CompanyEstListResponse, CompanyListEstimateUnitsResponse, CompanyCreateEstimateRequest, CompanyCreateEstimateResponse, CompanyCalculateRevisionRequest, CompanyCalculateRevisionResponse, CompanyListEstimateAcceptancesResponse, CompanyEstimateAcceptanceSubjectResponse, CompanyAcceptedBaselineReferenceResponse } from './company-estimating.generated';
export interface CompanyEstimateRecords { estimate: CompanyEstEstimateRecord; revision: CompanyEstRevisionRecord; snapshot: CompanyEstSnapshotRecord; rate: CompanyEstRateRecord; assembly: CompanyEstAssemblyRecord; conversion: CompanyEstConversionRecord }
const prefix = 'cipher_aec.estimating.company_api.';
export const companyEstimating = {
  list: <K extends 'estimate' | 'rate' | 'assembly' | 'conversion'>(company: string, kind: K, signal?: AbortSignal, cursor?: string) => rpc<Omit<CompanyEstListResponse, 'items'> & { items: CompanyEstimateRecords[K][] }>(prefix + 'list_records', { company, kind, cursor, limit: 50, count_mode: 'exact' }, false, signal),
  get: <K extends keyof CompanyEstimateRecords>(company: string, kind: K, record_id: string, signal?: AbortSignal) => rpc<CompanyEstimateRecords[K]>(prefix + 'get_record', { company, kind, record_id }, false, signal),
  units: (company: string, signal?: AbortSignal) => rpc<CompanyListEstimateUnitsResponse>(prefix + 'list_units', { company }, false, signal),
  create: (input: CompanyCreateEstimateRequest) => rpc<CompanyCreateEstimateResponse>(prefix + 'create_estimate', { ...input }, true),
  calculate: (input: CompanyCalculateRevisionRequest) => rpc<CompanyCalculateRevisionResponse>(prefix + 'calculate_revision', { ...input }, true),
  subject: (company: string, revision_id: string, signal?: AbortSignal) => rpc<CompanyEstimateAcceptanceSubjectResponse>(prefix + 'acceptance_subject', { company, revision_id }, false, signal),
  acceptedReference: (company: string, acceptance_id: string, signal?: AbortSignal) => rpc<CompanyAcceptedBaselineReferenceResponse>(prefix + 'accepted_baseline_reference', { company, acceptance_id }, false, signal),
  acceptances: (company: string, estimate_id: string, signal?: AbortSignal) => rpc<CompanyListEstimateAcceptancesResponse>(prefix + 'list_acceptances', { company, estimate_id }, false, signal),
};
export async function loadCompanyEstimate(company: string, id: string, signal: AbortSignal, revisionId?: string) {
  const estimate = await companyEstimating.get(company, 'estimate', id, signal);
  const selected = revisionId || estimate.current_revision;
  if (!selected) return { estimate };
  const revision = await companyEstimating.get(company, 'revision', selected, signal);
  if (revision.estimate !== id) throw new ApiError('This revision is unavailable for this Company estimate.', 'REVISION_UNAVAILABLE', 404);
  const snapshot = await companyEstimating.get(company, 'snapshot', revision.calculation_snapshot, signal);
  if (snapshot.estimate !== id || snapshot.subject_id !== revision.id) throw new ApiError('This snapshot is unavailable for this Company estimate revision.', 'SNAPSHOT_UNAVAILABLE', 404);
  return { estimate, revision, snapshot };
}
