import { rpc } from './client';
import type { TakeoffGetResponse, TakeoffListRequest, TakeoffListResponse, TakeoffCreateSetRequest, TakeoffCreateSetResponse, TakeoffCreateCalibrationRequest, TakeoffCreateCalibrationResponse, TakeoffCreateMeasurementRequest, TakeoffCreateMeasurementResponse, TakeoffBindLineRequest, TakeoffBindLineResponse, TakeoffImpactResponse, TakeoffCompareResponse } from './takeoff.generated';
import type { DomainApprovalPacket } from './contracts.generated';
const prefix = 'cipher_aec.takeoff.api.';
export const takeoff = {
  list: (input: TakeoffListRequest, signal?: AbortSignal) => rpc<TakeoffListResponse>(prefix + 'list_records', { ...input, limit: input.limit || 30, count_mode: 'exact' }, false, signal),
  get: (company: string, project: string, kind: 'set' | 'calibration' | 'measurement' | 'binding', record_id: string, signal?: AbortSignal) => rpc<TakeoffGetResponse>(prefix + 'get_record', { company, project, kind, record_id }, false, signal),
  createSet: (input: TakeoffCreateSetRequest) => rpc<TakeoffCreateSetResponse>(prefix + 'create_set', { ...input }, true),
  createCalibration: (input: TakeoffCreateCalibrationRequest) => rpc<TakeoffCreateCalibrationResponse>(prefix + 'create_calibration', { ...input }, true),
  createMeasurement: (input: TakeoffCreateMeasurementRequest) => rpc<TakeoffCreateMeasurementResponse>(prefix + 'create_measurement', { ...input }, true),
  bindLine: (input: TakeoffBindLineRequest) => rpc<TakeoffBindLineResponse>(prefix + 'bind_line', { ...input }, true),
  impact: (company: string, project: string, revision_id: string, signal?: AbortSignal) => rpc<TakeoffImpactResponse>(prefix + 'drawing_impact', { company, project, revision_id }, false, signal),
  compare: (company: string, project: string, before_id: string, after_id: string, signal?: AbortSignal) => rpc<TakeoffCompareResponse>(prefix + 'compare_measurements', { company, project, before_id, after_id }, false, signal),
  requestVerification: (input: { company: string; project: string; subject_id: string; expected_version: string; operation_id?: string }) => rpc<{ packet: DomainApprovalPacket; operation: { id: string; status: string; replayed: boolean } }>('cipher_aec.api.approvals.request_action', { ...input, action: 'calibration.verify.v1' }, true),
};
