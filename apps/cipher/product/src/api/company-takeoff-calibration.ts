import { ApiError, rpc } from './client';
import { companyTakeoff } from './company-takeoff';
import { bindingDigest } from './company-takeoff-binding';
import { invalidTakeoff, sameTakeoffValue as same, takeoffShape } from './company-takeoff-validation';
import type { CommandActor } from './company-takeoff-validation';
import type { PdfFrame } from '../PdfDrawing';
import type { CompanyDocumentRevision } from './company-documents.generated';
import type { CompanyTakeoffCalibrationRecord as Calibration, CompanyTakeoffCreateCalibrationRequest as Input, CompanyTakeoffCreateCalibrationResponse as Response, CompanyTakeoffGetResponse, CompanyListEstimateUnitsResponse, CompanyTakeoffPageGeometry } from './company-takeoff.generated';
export type CalibrationPlan = { documentId: string; revision: CompanyDocumentRevision; frame: PdfFrame; unit: CompanyListEstimateUnitsResponse['items'][number] };
export type SavedCalibration = { response: Response; plan: CalibrationPlan; authority: string };
export const createCalibration = (input: Input) => rpc<Response>('cipher_aec.takeoff.company_api.create_calibration', { company: input.company, operation_id: input.operation_id, takeoff_set: input.takeoff_set, source: input.source, definition: input.definition, conversion_ids: input.conversion_ids }, true);
export function calibrationInputs(input: Input, plan: CalibrationPlan) {
  const d = input.definition, q = d.known_distance, f = plan.frame, u = plan.unit;
  const anchors = d.anchors.flat();
  return takeoffShape('CompanyTakeoffCreateCalibrationRequest', input) && plan.revision.company === input.company && plan.revision.scope_type === 'Company' && plan.revision.project === null && !input.predecessor && input.conversion_ids.length === 0 && d.derived_units.length === 0 && d.title.trim().length > 0 && d.basis.trim().length > 0 && u.kind === 'uom' && u.fields.dimension === 'length' && u.id === q.unit_id && u.fields.precision === q.precision && /^\d+(\.\d+)?$/.test(q.amount) && Number(q.amount) > 0 && Number(q.amount) <= 1e9 && (q.amount.split('.')[1]?.length || 0) <= q.precision && Number(d.relative_numeric_tolerance) > 0 && Number(d.relative_numeric_tolerance) <= .01 && f.userUnit === 1 && [0,90,180,270].includes(f.rotation) && f.view.length === 4 && f.view.every(Number.isFinite) && f.view[2] > f.view[0] && f.view[3] > f.view[1] && anchors.every((v,i) => Number(v) >= f.view[i%2] && Number(v) <= f.view[i%2+2]) && !same(d.anchors[0].map(Number),d.anchors[1].map(Number)) && input.source.revision_id === plan.revision.id && input.source.source_sha256 === plan.revision.sha256 && input.source.source_sha256 === f.sourceSha256 && input.source.page >= 1 && input.source.page <= f.pageCount && f.pageCount === plan.revision.page_count;
}
export function calibrationFrame(frame: CompanyTakeoffPageGeometry, actual?: PdfFrame) {
  const crop=frame.crop_box.map(Number), media=frame.media_box.map(Number);
  return takeoffShape('CompanyTakeoffPageGeometry',frame) && crop[2]>crop[0] && crop[3]>crop[1] && media[2]>media[0] && media[3]>media[1] && crop.every((n,i)=>i<2?n>=media[i]:n<=media[i]) && (!actual || actual.userUnit===1 && frame.rotate===actual.rotation && same(crop,actual.view));
}
// Canonical Company manifests include their Company context plus the declared
// UOMs. Record ordering carries no meaning; additional undeclared masters do.
function calibrationManifest(r: Calibration) {
  const rows=r.unit_manifest.records, context=rows.filter(v=>v.kind==='company'), units=rows.filter(v=>v.kind==='uom');
  const expected=new Set([r.definition.known_distance.unit_id,...r.definition.derived_units.map(v=>v.output_unit_id),...r.unit_manifest.unit_conversions.flatMap(v=>[v.from_unit_id,v.to_unit_id])]);
  return context.length===1 && context[0].kind==='company' && context[0].fields.name===r.company && context[0].target?.doctype==='Company' && context[0].target.name===r.company && rows.length===expected.size+1 && units.length===expected.size && new Set(units.map(v=>v.id)).size===units.length && units.every(v=>expected.has(v.id));
}
export async function savedCalibration(value: CompanyTakeoffGetResponse) {
  if (!takeoffShape('CompanyTakeoffGetResponse',value) || !takeoffShape('CompanyTakeoffCalibrationRecord',value.record)) throw invalidTakeoff();
  const r=value.record as Calibration, s=r.source, q=r.definition.known_distance, u=r.unit_manifest.records.filter(v=>v.id===q.unit_id && v.kind==='uom');
  if (!calibrationManifest(r) || r.status!=='unverified' || r.project!==null || r.scope_type!=='Company' || s.project!==null || s.scope_type!=='Company' || s.company!==r.company || s.mime_type!=='application/pdf' || s.page>s.page_count || r.unit_manifest.dataset_id!==r.id || r.unit_manifest.scope.project!==null || r.unit_manifest.scope.scope_type!=='Company' || r.unit_manifest.scope.company!==r.company || u.length!==1 || u[0].kind!=='uom' || u[0].fields.dimension!=='length' || u[0].fields.precision!==q.precision || Number(q.amount)<=0 || Number(q.amount)>1e9 || (q.amount.split('.')[1]?.length||0)>q.precision || Number(r.definition.relative_numeric_tolerance)<=0 || Number(r.definition.relative_numeric_tolerance)>.01 || same(r.definition.anchors[0].map(Number),r.definition.anchors[1].map(Number)) || r.definition.anchors.flat().some((v,i)=>Number(v)<Number(r.page_geometry.crop_box[i%2])||Number(v)>Number(r.page_geometry.crop_box[i%2+2])) || !calibrationFrame(r.page_geometry) || !value.current_use || await bindingDigest(r)!==value.record_digest) throw invalidTakeoff();
  return {...value,record:r};
}
export async function matchesCalibration(result: Response, input: Input, actor: CommandActor, plan: CalibrationPlan) {
  if (!takeoffShape('CompanyTakeoffCreateCalibrationResponse',result) || !calibrationInputs(input,plan)) return false;
  const r=result.calibration, s=r.source;
  const scope=(v:{company:string;project:unknown;scope_type:string})=>v.company===input.company && v.project===null && v.scope_type==='Company';
  return scope(r) && scope(s) && scope(r.unit_manifest.scope) && r.author_person===actor.personId && r.author_user===actor.user && r.status==='unverified' && r.takeoff_set===input.takeoff_set && r.predecessor===null && r.revision_number===1 && same(r.definition,input.definition) && r.conversion_ids.length===0 && r.source_citations.length===0 && r.unit_manifest.dataset_id===r.id && calibrationManifest(r) && r.unit_manifest.records.length===2 && same(r.unit_manifest.records.find(v=>v.kind==='uom'),plan.unit) && r.unit_manifest.unit_conversions.length===0 && s.document_id===plan.documentId && s.revision_id===input.source.revision_id && s.source_sha256===input.source.source_sha256 && s.page===input.source.page && s.page_count===plan.revision.page_count && s.revision_number===plan.revision.revision_number && s.byte_length===plan.revision.byte_length && s.mime_type==='application/pdf' && s.is_current===true && s.current_revision===s.revision_id && s.current_revision_number===s.revision_number && calibrationFrame(r.page_geometry,plan.frame);
}
export async function calibrationPreflight(input: Input, plan: CalibrationPlan, signal: AbortSignal) {
  const detail=await companyTakeoff.source(input.company,plan.documentId,signal);
  const revision=detail.revisions.find(r=>r.id===input.source.revision_id);
  if (detail.document.current_revision!==input.source.revision_id || !same(revision,plan.revision)) throw new ApiError('The working drawing changed. Reopen the current source and review the calibration again.','calibration_review_changed',412);
}
export async function readCalibration(company: string, id: string, set: string, signal?: AbortSignal, expected?: Calibration, plan?: CalibrationPlan) {
  const result=await savedCalibration(await companyTakeoff.get(company,'calibration',id,signal,set));
  if (expected && !same(result.record,expected) || plan && !calibrationFrame(result.record.page_geometry,plan.frame)) throw invalidTakeoff();
  return result;
}
export async function listCalibrations(company:string,set:string,cursor?:string,signal?:AbortSignal) {
  const page=await companyTakeoff.list({company,kind:'calibration',takeoff_set:set,cursor},signal);
  await Promise.all(page.items.map(savedCalibration)); return page;
}
