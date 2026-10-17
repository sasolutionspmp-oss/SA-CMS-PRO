import { rpc } from './client';
import { sourceApi } from './sources';
import { invalidTakeoff, takeoffShape, validateSourceDetail, validateSourceList, validateSourcePage, validateTakeoffPage, validateTakeoffRecord } from './company-takeoff-validation';
import type { CompanyTakeoffCreateSetRequest, CompanyTakeoffCreateSetResponse, CompanyTakeoffCreateMeasurementRequest, CompanyTakeoffCreateMeasurementResponse, CompanyTakeoffGetResponse, CompanyTakeoffListRequest, CompanyTakeoffListResponse, CompanyListEstimateUnitsResponse } from './company-takeoff.generated';
import type { CompanyDocumentDetail, CompanyDocumentList, CompanyDocumentPreview, CompanyDocumentRevision } from './company-documents.generated';
const prefix = 'cipher_aec.takeoff.company_api.';
export const companyTakeoff = {
  async list(input: CompanyTakeoffListRequest, signal?: AbortSignal) {
    const request = { company: input.company, kind: input.kind, takeoff_set: input.takeoff_set, cursor: input.cursor, limit: 25, count_mode: 'none' as const };
    return validateTakeoffPage(await rpc<CompanyTakeoffListResponse>(prefix + 'list_records', request, false, signal), request);
  },
  async get(company: string, kind: CompanyTakeoffListRequest['kind'], record_id: string, signal?: AbortSignal, takeoff_set?: string) {
    return validateTakeoffRecord(await rpc<CompanyTakeoffGetResponse>(prefix + 'get_record', { company, kind, record_id }, false, signal), { company, kind, takeoff_set }, record_id);
  },
  createSet: (input: CompanyTakeoffCreateSetRequest) => rpc<CompanyTakeoffCreateSetResponse>(prefix + 'create_set', { company: input.company, operation_id: input.operation_id, title: input.title, discipline: input.discipline, drawing_package: input.drawing_package, basis: input.basis }, true),
  createMeasurement: (input: CompanyTakeoffCreateMeasurementRequest) => rpc<CompanyTakeoffCreateMeasurementResponse>(prefix + 'create_measurement', { company: input.company, operation_id: input.operation_id, takeoff_set: input.takeoff_set, source: input.source, definition: input.definition, conversion_ids: input.conversion_ids }, true),
  async units(company: string, signal?: AbortSignal) {
    const result = await rpc<CompanyListEstimateUnitsResponse>('cipher_aec.estimating.company_api.list_units', { company }, false, signal);
    if (!takeoffShape('CompanyListEstimateUnitsResponse', result) || new Set(result.items.map(row => row.id)).size !== result.items.length) throw invalidTakeoff();
    return result;
  },
  async sources(company: string, signal?: AbortSignal) { return validateSourceList(await sourceApi({ type: 'Company', company }).list(signal) as CompanyDocumentList, company); },
  async source(company: string, documentId: string, signal?: AbortSignal) { return validateSourceDetail(await sourceApi({ type: 'Company', company }).document(documentId, signal) as CompanyDocumentDetail, company, documentId); },
  async page(company: string, documentId: string, revision: CompanyDocumentRevision, page: number, signal?: AbortSignal) { return validateSourcePage(await sourceApi({ type: 'Company', company }).preview(revision.id, page, signal) as CompanyDocumentPreview, company, documentId, revision, page); },
};
