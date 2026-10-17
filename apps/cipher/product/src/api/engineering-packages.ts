import schema from '../../../platform/apps/cipher_aec/cipher_aec/engineering_packages/schemas/api-v1.schema.json' with { type: 'json' };
import coreSchema from '../../../platform/apps/cipher_aec/cipher_aec/api/schema.json' with { type: 'json' };
import { api, ApiError, rpc } from './client';
import { engineeringDigest, type Actor, type Scope } from './engineering';
import { sameValue, schemaShape } from './schema-validation';
import type * as E from './engineering-packages.generated';
import type { ApprovalCommandResponse, EngineeringPackageApprovalPacket, EngineeringPackageApprovalExecutionResponse } from './contracts.generated';
export type PackageKind = E.EpGetRecordRequest['kind'];
export const packageAction = { basis: 'engineering.basis.check.v1', calculation: 'engineering.calculation.check.v1', deliverable: 'engineering.deliverable.check.v1' } as const;
const prefix = 'cipher_aec.engineering_packages.api.';
const recordDefs: Record<PackageKind, string> = { package: 'EpPackage', package_revision: 'EpPackageRevision', basis: 'EpBasis', calculation: 'EpCalculation', deliverable: 'EpDeliverable', check: 'EpCheck' };
export const packageShape = (name: string, value: unknown) => schemaShape(schema, name, value);
export const invalidPackage = () => new ApiError('The engineering package reply could not be matched to the exact project, sources and reviewed revision.', 'INVALID_CONTRACT', 200);
const scoped = (value: E.EpRecord, scope: Scope) => value.company === scope.company && value.project === scope.project && value.scope_type === 'Project';
export async function validatePackageRecord(value: E.EpGetResponse, scope: Scope, kind: PackageKind, id?: string, parent?: string) {
  if (!packageShape('EpGetResponse', value) || !packageShape(recordDefs[kind], value.record) || !scoped(value.record, scope) || id && value.record.id !== id || parent && (!('parent_id' in value.record) || value.record.parent_id !== parent) || await engineeringDigest(value.record) !== value.record_digest) throw invalidPackage();
  const r = value.record;
  if (['basis', 'calculation', 'deliverable'].includes(kind) !== Boolean(value.review)) throw invalidPackage();
  if ('unit_manifest' in r) {
    const m = r.unit_manifest, quantities = 'quantities' in r ? r.quantities : [...r.inputs, ...r.outputs];
    const unitIds = new Set(quantities.map(row => row.quantity.unit_id));
    const companies = m.records.filter(row => row.kind === 'company'), units = m.records.filter(row => row.kind === 'uom');
    if (m.dataset_id !== r.id || !sameValue(m.scope, { company: scope.company, project: scope.project }) || m.unit_conversions.length || companies.length !== 1 || companies[0].kind !== 'company' || companies[0].fields.name !== scope.company || units.length !== unitIds.size || units.some(row => row.kind !== 'uom' || !unitIds.has(row.id) || !row.target || row.target.doctype !== 'UOM') || quantities.some(row => { const u = units.find(unit => unit.id === row.quantity.unit_id); return !u || u.kind !== 'uom' || row.quantity.precision !== u.fields.precision; })) throw invalidPackage();
  }
  return value;
}
export type PackageBasis = { header: E.EpGetResponse; revision: E.EpGetResponse; basis?: E.EpGetResponse; predecessor?: E.EpGetResponse; calculations?: E.EpGetResponse[] };
type Requests = { create_package: E.EpCreatePackageRequest; revise_package: E.EpRevisePackageRequest; create_basis: E.EpCreateBasisRequest; create_calculation: E.EpCreateCalculationRequest; create_deliverable: E.EpCreateDeliverableRequest };
type Replies = { create_package: E.EpCreatePackageResponse; revise_package: E.EpRevisePackageResponse; create_basis: E.EpCreateBasisResponse; create_calculation: E.EpCreateCalculationResponse; create_deliverable: E.EpCreateDeliverableResponse };
const commandDefs: { [K in keyof Requests]: [string, string] } = { create_package: ['EpCreatePackageRequest', 'EpCreatePackageResponse'], revise_package: ['EpRevisePackageRequest', 'EpRevisePackageResponse'], create_basis: ['EpCreateBasisRequest', 'EpCreateBasisResponse'], create_calculation: ['EpCreateCalculationRequest', 'EpCreateCalculationResponse'], create_deliverable: ['EpCreateDeliverableRequest', 'EpCreateDeliverableResponse'] };
export type PackageCommand = ({ [K in keyof Requests]: { kind: K; payload: Omit<Requests[K], 'operation_id'>; basis?: PackageBasis } }[keyof Requests]) | { kind: 'request_check'; payload: Scope; subject: E.EpGetResponse; subjectKind: 'basis' | 'calculation' | 'deliverable' } | { kind: 'check_action'; payload: Scope; packet: EngineeringPackageApprovalPacket; action: 'Grant' | 'Reject' | 'execute' | 'withdraw'; reason: string };
export type PackageReply = Replies[keyof Replies] | ApprovalCommandResponse | EngineeringPackageApprovalExecutionResponse;
const referenceKey = (row: Record<string, unknown>, kind: string) => JSON.stringify([row.revision_id, row.source_sha256, ...(kind === 'source_citations' ? [row.page, row.excerpt_sha256] : kind === 'drawing_references' ? [row.page, row.locator] : [])]);
function closureMatches(actual: object[], expected: object[], kind: string) {
  const keys = new Set(expected.map(row => referenceKey(row as Record<string, unknown>, kind)));
  return actual.length === keys.size && expected.every(row => actual.some(value => referenceKey(value as Record<string, unknown>, kind) === referenceKey(row as Record<string, unknown>, kind) && Object.entries(row).every(([key, field]) => sameValue((value as Record<string, unknown>)[key], field))));
}
export function validatePackagePacket(packet: EngineeringPackageApprovalPacket, scope: Scope, id?: string) {
  if (!schemaShape(coreSchema, 'EngineeringPackageApprovalPacket', packet) || packet.company !== scope.company || packet.project !== scope.project || id && packet.id !== id || packet.review_manifest.subject.name !== packet.subject.id || packet.review_manifest.subject.doctype !== packet.subject.type || packet.review_manifest.effect.subject_id !== packet.subject.id || packet.review_manifest.effect.action !== packet.action || packet.review_manifest.effect.subject_digest !== packet.source_version) throw invalidPackage();
  return packet;
}
export async function validatePackageManifestSubject(packet: EngineeringPackageApprovalPacket, subject: E.EpGetResponse, kind: 'basis' | 'calculation' | 'deliverable') {
  const scope = { company: subject.record.company, project: subject.record.project };
  await validatePackageRecord(subject, scope, kind);
  validatePackagePacket(packet, scope);
  const value = subject.record as E.EpBasis | E.EpCalculation | E.EpDeliverable;
  const type = { basis: 'Cipher Design Basis Revision', calculation: 'Cipher Calculation Revision', deliverable: 'Cipher Deliverable Revision' }[kind];
  const effect = { schema: 'cipher.engineering.package-check.v1', action: packageAction[kind], subject_kind: kind, subject_id: value.id, subject_digest: subject.record_digest, parent_id: value.parent_id, package_revision: value.package_revision, package_digest: value.package_digest, preparer_person: value.author_person, checker: value.checker, outcome: 'checked', issue_authorized: false, sealed: false };
  const sources = [{ source_citations: value.source_citations, drawing_references: value.drawing_references, artifacts: value.artifacts, unit_manifest: 'unit_manifest' in value ? value.unit_manifest : null }];
  const summary = { definition: value.definition, inputs: 'inputs' in value ? value.inputs : 'quantities' in value ? value.quantities : [], outputs: 'outputs' in value ? value.outputs : [], calculations: 'calculations' in value ? value.calculations : [], no_effects: value.no_effects, solver_executed: false, issue_authorized: false, sealed: false };
  const manifest = packet.review_manifest;
  if (packet.action !== packageAction[kind] || packet.subject.type !== type || packet.subject.id !== value.id || packet.source_version !== subject.record_digest || packet.requester.id !== value.author_person || !sameValue(manifest.effect, effect) || !sameValue(manifest.sources, sources) || !sameValue(manifest.summary, summary) || await engineeringDigest(manifest) !== packet.manifest_hash) throw invalidPackage();
  return packet;
}
export const engineeringPackages = {
  async get(scope: Scope, kind: PackageKind, id: string, signal?: AbortSignal) { return validatePackageRecord(await rpc<E.EpGetResponse>(prefix + 'get_record', { ...scope, kind, record_id: id }, false, signal), scope, kind, id); },
  async list(scope: Scope, kind: PackageKind, parent_id?: string, cursor?: string, signal?: AbortSignal) {
    const value = await rpc<E.EpListResponse>(prefix + 'list_records', { ...scope, kind, parent_id, cursor, limit: 25, count_mode: 'none' }, false, signal);
    if (!packageShape('EpListResponse', value) || value.limit !== 25 || value.items.length > 25 || cursor && cursor === value.next_cursor || new Set(value.items.map(row => row.record.id)).size !== value.items.length) throw invalidPackage();
    await Promise.all(value.items.map(row => validatePackageRecord(row, scope, kind, undefined, parent_id))); return value;
  },
  async people(scope: Scope, role: 'engineer' | 'checker', cursor?: string, signal?: AbortSignal) { const value = await rpc<E.EpPeopleResponse>(prefix + 'list_people', { ...scope, role, cursor, limit: 25, count_mode: 'none' }, false, signal); if (!packageShape('EpPeopleResponse', value) || value.limit !== 25 || cursor && cursor === value.next_cursor || new Set(value.items.map(row => row.user)).size !== value.items.length) throw invalidPackage(); return value; },
  async units(scope: Scope, cursor?: string, signal?: AbortSignal) { const value = await rpc<E.EpUnitsResponse>(prefix + 'list_units', { ...scope, cursor, limit: 25, count_mode: 'none' }, false, signal); if (!packageShape('EpUnitsResponse', value) || value.limit !== 25 || cursor && cursor === value.next_cursor || new Set(value.items.map(row => row.id)).size !== value.items.length) throw invalidPackage(); return value; },
  async packet(scope: Scope, id: string, signal?: AbortSignal) { return validatePackagePacket(await api.approval(scope.company, scope.project, id, signal) as EngineeringPackageApprovalPacket, scope, id); },
  async send(command: PackageCommand & { operation_id: string }, actor: Actor): Promise<PackageReply> {
    if (command.kind === 'request_check') {
      const subject = command.subject.record;
      if (!['basis', 'calculation', 'deliverable'].includes(command.subjectKind) || !('package_revision' in subject) || !('definition' in subject)) throw invalidPackage();
      const result = await rpc<ApprovalCommandResponse>('cipher_aec.api.approvals.request_action', { ...command.payload, action: packageAction[command.subjectKind], subject_id: subject.id, expected_version: command.subject.record_digest, operation_id: command.operation_id }, true);
      if (!schemaShape(coreSchema, 'ApprovalCommandResponse', result)) throw invalidPackage();
      const packet = validatePackagePacket(result.packet as EngineeringPackageApprovalPacket, command.payload);
      await validatePackageManifestSubject(packet, command.subject, command.subjectKind);
      if (packet.requester.id !== actor.personId) throw invalidPackage();
      return result;
    }
    if (command.kind === 'check_action') {
      const packet = command.packet, action = command.action;
      const result = await api.approvalAction(action, { ...command.payload, packet_id: packet.id, manifest_hash: packet.manifest_hash, reason: command.reason, operation_id: command.operation_id });
      if (!schemaShape(coreSchema, action === 'execute' ? 'EngineeringPackageApprovalExecutionResponse' : 'ApprovalCommandResponse', result)) throw invalidPackage();
      const current = validatePackagePacket(result.packet as EngineeringPackageApprovalPacket, command.payload, packet.id);
      if (current.manifest_hash !== packet.manifest_hash || !sameValue(current.review_manifest, packet.review_manifest)) throw invalidPackage();
      if (action === 'execute') {
        const check = (result as EngineeringPackageApprovalExecutionResponse).effect.check, effect = packet.review_manifest.effect;
        if (!scoped(check, command.payload) || check.author_user !== actor.user || check.author_person !== actor.personId || check.packet_id !== packet.id || !['subject_kind', 'subject_id', 'subject_digest', 'parent_id', 'package_revision', 'package_digest', 'preparer_person', 'checker', 'outcome', 'issue_authorized', 'sealed'].every(key => sameValue(check[key as keyof E.EpCheck], effect[key as keyof typeof effect])) || !packet.decisions.some(decision => decision.id === check.decision_id && decision.actor.id === check.checker.person && decision.decision === 'Grant' && decision.reason === check.comments) || current.state !== 'Consumed') throw invalidPackage();
      } else if (action !== 'withdraw' && !current.decisions.some(decision => decision.actor.id === actor.personId && decision.decision === action && decision.reason === command.reason)) throw invalidPackage();
      return result as PackageReply;
    }
    const input = { ...command.payload, operation_id: command.operation_id } as Requests[keyof Requests];
    if (!packageShape(commandDefs[command.kind][0], input)) throw new ApiError('Complete the package fields and exact source selections before saving.', 'package_input', 422);
    const result = await rpc<Replies[keyof Replies]>(prefix + command.kind, input as unknown as Record<string, unknown>, true);
    if (!packageShape(commandDefs[command.kind][1], result)) throw invalidPackage();
    const body = result as unknown as Record<string, E.EpRecord>, header = body.package as E.EpPackage, authored = (body.revision || body.basis || body.calculation || body.deliverable) as E.EpPackageRevision | E.EpBasis | E.EpCalculation | E.EpDeliverable;
    const p = input as unknown as Record<string, unknown>;
    if (!scoped(header, input) || !scoped(authored, input) || authored.author_person !== actor.personId || authored.author_user !== actor.user || authored.parent_id !== header.id || !sameValue(authored.definition, input.definition)) throw invalidPackage();
    if ('source_citations' in authored) {
      const inherited = command.kind === 'create_basis' ? [] : [command.basis?.basis?.record, ...(command.kind === 'create_deliverable' ? command.basis?.calculations?.map(row => row.record) || [] : [])].filter(Boolean) as (E.EpBasis | E.EpCalculation)[];
      for (const kind of ['source_citations', 'drawing_references', 'artifacts'] as const) {
        const expected = [...inherited.flatMap(row => row[kind] as object[]), ...((p[kind] as object[] | undefined) || [])];
        if (!closureMatches(authored[kind], expected, kind)) throw invalidPackage();
      }
    }
    if (command.kind === 'create_package' || command.kind === 'revise_package') {
      const assignment = authored as E.EpPackageRevision, definition = input.definition as E.EpPackageDefinition;
      if (assignment.responsible.user !== definition.responsible_user || assignment.checker.user !== definition.checker_user || assignment.responsible.person === assignment.checker.person) throw invalidPackage();
    }
    if (command.kind === 'create_package') { if (header.author_person !== actor.personId || header.author_user !== actor.user || header.current_revision !== authored.id || header.revision_number !== 1 || header.basis_head !== null || header.calculation_heads.length || header.deliverable_heads.length || authored.predecessor !== null || authored.revision_number !== 1) throw invalidPackage(); }
    else {
      const basis = command.basis, original = basis?.header.record as E.EpPackage | undefined;
      if (!original || basis?.header.record_digest !== p.expected_version || original.id !== header.id || header.author_person !== original.author_person || header.author_user !== original.author_user || header.created_at !== original.created_at || header.number !== original.number) throw invalidPackage();
      let expectedHeader: E.EpPackage;
      if (command.kind === 'revise_package') {
        if (authored.predecessor !== original.current_revision || authored.revision_number !== original.revision_number + 1) throw invalidPackage();
        expectedHeader = { ...original, current_revision: authored.id, revision_number: authored.revision_number };
      }
      else {
        const assignment = basis!.revision.record as E.EpPackageRevision;
        if (!('package_revision' in authored) || assignment.id !== original.current_revision || assignment.parent_id !== original.id || assignment.revision_number !== original.revision_number || assignment.responsible.person !== actor.personId || authored.package_revision !== original.current_revision || authored.package_digest !== basis!.revision.record_digest || !sameValue(authored.checker, assignment.checker)) throw invalidPackage();
        const previous = (command.kind === 'create_basis' ? basis!.basis?.record : basis!.predecessor?.record) as E.EpBasis | E.EpCalculation | E.EpDeliverable | undefined;
        if (authored.predecessor !== (previous?.id || null) || authored.revision_number !== (previous?.revision_number || 0) + 1 || previous && authored.family_id !== previous.family_id) throw invalidPackage();
        if (command.kind === 'create_basis') {
          if (!sameValue((authored as E.EpBasis).quantities, p.quantities)) throw invalidPackage();
          expectedHeader = { ...original, basis_head: authored.id };
        }
        else {
          if (!('basis_revision' in authored) || authored.basis_revision !== basis?.basis?.record.id || authored.basis_digest !== basis.basis.record_digest) throw invalidPackage();
          if (command.kind === 'create_calculation') {
            const calc = authored as E.EpCalculation, source = basis.basis!.record as E.EpBasis, selected = (p.input_keys as string[]).map(key => source.quantities.find(row => row.key === key));
            if (!sameValue(calc.input_keys, p.input_keys) || !sameValue(calc.inputs, selected) || !sameValue(calc.outputs, p.outputs) || calc.inputs.some(row => !sameValue(calc.unit_manifest.records.find(unit => unit.kind === 'uom' && unit.id === row.quantity.unit_id), source.unit_manifest.records.find(unit => unit.kind === 'uom' && unit.id === row.quantity.unit_id)))) throw invalidPackage();
            expectedHeader = { ...original, calculation_heads: [...original.calculation_heads.filter(id => id !== (previous?.id || null)), authored.id] };
          }
          else {
            if (!sameValue((authored as E.EpDeliverable).calculations, p.calculations)) throw invalidPackage();
            expectedHeader = { ...original, deliverable_heads: [...original.deliverable_heads.filter(id => id !== (previous?.id || null)), authored.id] };
          }
        }
      }
      if (!sameValue(header, expectedHeader)) throw invalidPackage();
    }
    if ('unit_manifest' in authored) await validatePackageRecord({ record: authored, record_digest: await engineeringDigest(authored), review: { state: 'working', check_id: null, packet_id: null, issue_authorized: false } }, input, command.kind === 'create_basis' ? 'basis' : 'calculation', authored.id);
    return result;
  },
};
