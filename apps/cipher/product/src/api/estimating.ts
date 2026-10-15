import { ApiError, rpc } from './client';
import type { EstEstimateRecord, EstRateRecord, EstAssemblyRecord, EstConversionRecord, EstRevisionRecord, EstSnapshotRecord, EstLineRecord, EstListResponse, ListEstimateUnitsResponse, CreateEstimateRequest, CreateEstimateResponse, CalculateRevisionRequest, CalculateRevisionResponse } from './estimating.generated';

export interface EstimateRecords { estimate: EstEstimateRecord; rate: EstRateRecord; assembly: EstAssemblyRecord; conversion: EstConversionRecord; revision: EstRevisionRecord; snapshot: EstSnapshotRecord; line: EstLineRecord }
const prefix = 'cipher_aec.estimating.api.';
function requireReceipt(data: CreateEstimateResponse | CalculateRevisionResponse, operationId: string, calculation = false) {
  if (!data || data.operation?.id !== operationId || data.operation.status !== 'succeeded' || typeof data.operation.replayed !== 'boolean' || typeof data.estimate?.id !== 'string' || (calculation && (!('revision' in data) || typeof data.revision?.id !== 'string' || typeof data.calculation?.id !== 'string'))) {
    throw new ApiError('The workspace returned an incomplete operation receipt. Recover the original request.', 'INVALID_CONTRACT', 200);
  }
}
export const estimating = {
  list: <K extends 'estimate' | 'rate' | 'assembly' | 'conversion'>(company: string, project: string, kind: K, signal?: AbortSignal, cursor?: string) => rpc<Omit<EstListResponse, 'items'> & { items: EstimateRecords[K][] }>(`${prefix}list_records`, { company, project, kind, limit: 50, count_mode: 'exact', cursor }, false, signal),
  get: <K extends keyof EstimateRecords>(company: string, project: string, kind: K, record_id: string, signal?: AbortSignal) => rpc<EstimateRecords[K]>(`${prefix}get_record`, { company, project, kind, record_id }, false, signal),
  units: (company: string, project: string, signal?: AbortSignal) => rpc<ListEstimateUnitsResponse>(`${prefix}list_units`, { company, project }, false, signal),
  async create(input: CreateEstimateRequest & { operation_id: string }) { const data = await rpc<CreateEstimateResponse>(`${prefix}create_estimate`, { ...input }, true); requireReceipt(data, input.operation_id); return data; },
  async calculate(input: CalculateRevisionRequest & { operation_id: string }) { const data = await rpc<CalculateRevisionResponse>(`${prefix}calculate_revision`, { ...input }, true); requireReceipt(data, input.operation_id, true); return data; },
};

export async function loadEstimate(company: string, project: string, id: string, signal: AbortSignal, revisionId?: string) {
  const estimate = await estimating.get(company, project, 'estimate', id, signal);
  const selected = revisionId || estimate.current_revision;
  if (!selected) return { estimate };
  const revision = await estimating.get(company, project, 'revision', selected, signal);
  if (revision.estimate !== estimate.id) throw new ApiError('This revision is unavailable for this estimate.', 'REVISION_UNAVAILABLE', 404);
  const snapshot = await estimating.get(company, project, 'snapshot', revision.calculation_snapshot, signal);
  if (snapshot.subject_id !== revision.id) throw new ApiError('This calculation is unavailable for this revision.', 'SNAPSHOT_UNAVAILABLE', 404);
  return { estimate, revision, snapshot };
}
export type EstimateView = Awaited<ReturnType<typeof loadEstimate>>;
