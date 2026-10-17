import { companyDraftSaveSchema } from './company-draft-saves.generated';
import type { CompanyDraftSaveSubject, CompanyDraftSaveResponse, CompanyDraftSaveCore, CompanyDraftSaveCanonicalResult, CompanyDraftSaveRequest, ComRevision, CompanyEstRevisionRecord, CompanyEstSnapshotRecord } from './company-draft-saves.generated';
import type { CompanyEstLineRecord, CompanyEstConversionRecord } from './company-estimating.generated';
import type { CompanyRickyProposalResponse as Suggestion } from './company-ricky-proposals.generated';
import { suggestionDigest } from './company-ricky-proposals-validation';
import { sameSelectedValue as same } from './company-ricky-validation';

type Shape = Record<string, unknown>;
const defs = companyDraftSaveSchema.$defs as unknown as Record<string, Shape>;
const record = (value: unknown): value is Shape => Boolean(value && typeof value === 'object' && !Array.isArray(value));
const keywords = new Set(['$ref', '$comment', 'title', 'type', 'properties', 'required', 'additionalProperties', 'maxProperties', 'items', 'minItems', 'maxItems', 'minLength', 'maxLength', 'minimum', 'maximum', 'format', 'pattern', 'enum', 'const', 'oneOf', 'anyOf']);
const isType = (value: unknown, type: string) => type === 'null' ? value === null : type === 'array' ? Array.isArray(value) : type === 'object' ? record(value) : type === 'integer' ? Number.isSafeInteger(value) : type === 'number' ? typeof value === 'number' && Number.isFinite(value) : ['string','boolean'].includes(type) && typeof value === type;

// Finite evaluator for the published draft contract and its canonical dependencies.
// Unknown constraints are rejected. This never substitutes for server authority.
function shape(value: unknown, schema: Shape, depth = 0): boolean {
  if (depth > 64 || Object.keys(schema).some(key => !keywords.has(key))) return false;
  if (schema.$ref) {
    const name = String(schema.$ref).replace(/^#\/\$defs\//, '');
    if (!defs[name] || !shape(value, defs[name], depth + 1)) return false;
  }
  if (schema.type && !(Array.isArray(schema.type) ? schema.type : [schema.type]).some(type => isType(value, String(type)))) return false;
  if (schema.oneOf && (schema.oneOf as Shape[]).filter(branch => shape(value, branch, depth + 1)).length !== 1) return false;
  if (schema.anyOf && !(schema.anyOf as Shape[]).some(branch => shape(value, branch, depth + 1))) return false;
  if (Object.hasOwn(schema, 'const') && !same(value, schema.const) || schema.enum && !(schema.enum as unknown[]).some(item => same(value, item))) return false;
  if (record(value)) {
    const properties = (schema.properties || {}) as Record<string, Shape>;
    if ((schema.required as string[] || []).some(key => !Object.hasOwn(value, key)) || typeof schema.maxProperties === 'number' && Object.keys(value).length > schema.maxProperties) return false;
    for (const [key, item] of Object.entries(value)) {
      if (Object.hasOwn(properties, key)) { if (!shape(item, properties[key], depth + 1)) return false; }
      else if (schema.additionalProperties === false || record(schema.additionalProperties) && !shape(item, schema.additionalProperties, depth + 1)) return false;
    }
  }
  if (Array.isArray(value) && (typeof schema.minItems === 'number' && value.length < schema.minItems || typeof schema.maxItems === 'number' && value.length > schema.maxItems || record(schema.items) && !value.every(item => shape(item, schema.items as Shape, depth + 1)))) return false;
  if (typeof value === 'string') {
    if (typeof schema.minLength === 'number' && [...value].length < schema.minLength || typeof schema.maxLength === 'number' && [...value].length > schema.maxLength || schema.pattern && !new RegExp(String(schema.pattern)).test(value)) return false;
    if (schema.format === 'uuid' && !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value)) return false;
    if (schema.format === 'date' && (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value)) return false;
    if (schema.format === 'date-time' && (!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) || Number.isNaN(Date.parse(value)))) return false;
    if (schema.format && !['uuid','date','date-time'].includes(String(schema.format))) return false;
  }
  return !(typeof value === 'number' && (typeof schema.minimum === 'number' && value < schema.minimum || typeof schema.maximum === 'number' && value > schema.maximum));
}
export const publishedDraftSaveShape = (name: keyof typeof companyDraftSaveSchema.$defs, value: unknown) => Boolean(defs[name] && shape(value, defs[name]));
export type DraftSaveBase = { kind: 'scope'; revision: ComRevision } | { kind: 'estimate'; revision: CompanyEstRevisionRecord; snapshot: CompanyEstSnapshotRecord; lines: CompanyEstLineRecord[]; conversions: CompanyEstConversionRecord[] };
export type DraftSaveBinding = { proposal: Suggestion; subject: CompanyDraftSaveSubject; user: string; person: string };
const reference = (row: { revision_id: string; page: number; excerpt_sha256: string; source_sha256?: string }) => ({ revision_id: row.revision_id, page: row.page, excerpt_sha256: row.excerpt_sha256, source_sha256: row.source_sha256 });
const omit = (value: object, fields: string[]) => Object.fromEntries(Object.entries(value).filter(([key]) => !fields.includes(key)));
const companyRecord = (value: { company: string; scope_type: string; project: unknown }, company: string) => value.company === company && value.scope_type === 'Company' && value.project === null;
const originalDigest = (proposal: Suggestion, kind: string, id: string) => proposal.source_manifest.records.find(row => row.kind === kind && row.id === id)?.digest;

export function exactDraftDecimal(numerator: string, denominator: string, precision: number): string | undefined {
  if (!/^(0|[1-9][0-9]*)$/.test(numerator) || !/^[1-9][0-9]*$/.test(denominator) || !Number.isInteger(precision) || precision < 0 || precision > 12) return;
  const n = BigInt(numerator), d = BigInt(denominator), scale = 10n ** BigInt(precision);
  if (n * scale % d !== 0n) return;
  const digits = (n * scale / d).toString().padStart(precision + 1, '0');
  return precision ? `${digits.slice(0, -precision)}.${digits.slice(-precision)}`.replace(/0+$/, '').replace(/\.$/, '') : digits;
}

async function matchesPayload(subject: CompanyDraftSaveSubject, proposal: Suggestion, base: DraftSaveBase): Promise<boolean> {
  const payload = subject.payload, prepared = proposal.preparation;
  const head = proposal.source_manifest.preparation_heads.find(row => row.domain === (base.kind === 'scope' ? 'commercial' : 'estimate'));
  if (!head || base.revision.id !== head.revision_id || base.revision.company !== proposal.company || await suggestionDigest(base.revision) !== head.digest) return false;
  if (base.kind === 'scope') {
    if (!publishedDraftSaveShape('ComRevision', base.revision) || prepared.kind !== 'scope-draft.v1' || !('composition' in payload) || payload.proposal_id !== head.owner_id || base.revision.proposal !== head.owner_id || payload.expected_revision !== base.revision.revision_number || payload.expected_native_fingerprint !== base.revision.native_fingerprint) return false;
    const old = base.revision.composition, next = payload.composition;
    if (!same(omit(old, ['sections','source_references']), omit(next, ['sections','source_references'])) || !same(next.sections.slice(0, old.sections.length), old.sections)) return false;
    const appended = next.sections.slice(old.sections.length);
    const expected = [...prepared.proposed_fields.sections.map(row => ({ kind: 'scope', title: 'Unverified author suggestion: ' + row.heading, text: row.text })), ...prepared.unverified_claims.map(text => ({ kind: 'assumption', title: 'Unverified author statement', text }))];
    if (new Set(next.sections.map(row => row.id)).size !== next.sections.length || !same(appended.map(row => omit(row, ['id'])), expected)) return false;
    const refs = structuredClone(old.source_references || []);
    for (const source of prepared.verified_source_references) {
      const existing = refs.find(row => row.revision_id === source.revision_id && row.page === source.page);
      if (existing && !same(reference(existing), reference(source))) return false;
      if (!existing) refs.push({ ...reference(source), source_sha256: source.source_sha256, purpose: 'Human-reviewed unverified author suggestion', permission_basis: 'Current canonical source authorization' });
    }
    return same(next.source_references, refs);
  }
  if (!publishedDraftSaveShape('CompanyEstRevisionRecord', base.revision) || !publishedDraftSaveShape('CompanyEstSnapshotRecord', base.snapshot) || !companyRecord(base.revision, proposal.company) || !companyRecord(base.snapshot, proposal.company) || prepared.kind !== 'estimate-draft.v1' || !('lines' in payload) || payload.estimate_id !== head.owner_id || base.revision.estimate !== head.owner_id || payload.expected_revision !== base.revision.id || base.snapshot.subject_id !== base.revision.id || base.snapshot.estimate !== head.owner_id || base.snapshot.id !== base.revision.calculation_snapshot || await suggestionDigest(base.snapshot) !== originalDigest(proposal, 'snapshot', base.snapshot.id)) return false;
  const inputs = base.snapshot.inputs, lines = structuredClone(inputs.lines);
  for (const selected of prepared.proposed_fields.quantity_selections) {
    const record = base.lines.find(row => row.id === selected.line_record_id);
    if (!record || !companyRecord(record, proposal.company) || record.estimate_revision !== base.revision.id || await suggestionDigest(record) !== originalDigest(proposal, 'line', record.id)) return false;
    const authored = lines.find(row => row.line_id === record.line_id);
    if (!authored || !same(authored, record.authored) || authored.quantity.unit_id !== selected.quantity.target_unit_id) return false;
    const amount = exactDraftDecimal(selected.quantity.numerator, selected.quantity.denominator, authored.quantity.precision);
    if (amount === undefined) return false;
    authored.quantity.amount = amount;
  }
  const conversions: string[] = [];
  for (const definition of inputs.unit_manifest.unit_conversions) {
    const matching = base.conversions.filter(row => same(row.definition, definition));
    if (matching.length !== 1 || matching[0].id !== definition.id || !companyRecord(matching[0], proposal.company)) return false;
    const pinned = originalDigest(proposal, 'conversion', matching[0].id);
    if (pinned && await suggestionDigest(matching[0]) !== pinned) return false;
    conversions.push(matching[0].id);
  }
  const refs = inputs.basis_citations.map(reference);
  for (const source of prepared.verified_source_references) {
    const existing = refs.find(row => row.revision_id === source.revision_id && row.page === source.page);
    if (existing && !same(existing, reference(source))) return false;
    if (!existing) refs.push(reference(source));
  }
  const notes = [inputs.basis_description, ...(prepared.proposed_fields.notes ? ['Unverified author suggestion: ' + prepared.proposed_fields.notes] : []), ...prepared.unverified_claims.map(text => 'Unverified author statement: ' + text)].join('; ');
  return same(payload.lines, lines) && same(payload.adjustments, inputs.adjustments) && same(payload.conversion_ids, [...new Set(conversions)].sort()) && payload.basis_description === notes && same(payload.basis_citations, refs);
}

async function matchesApplication(core: CompanyDraftSaveCore, saved: CompanyDraftSaveCanonicalResult, binding: DraftSaveBinding): Promise<boolean> {
  const { proposal, subject, user, person } = binding;
  const scope = proposal.action === 'aec.scope.draft', head = proposal.source_manifest.preparation_heads.find(row => row.domain === (scope ? 'commercial' : 'estimate'));
  if (!head || core.company !== proposal.company || core.user !== user || core.person !== person || core.proposal_id !== proposal.id || core.proposal_version !== proposal.version || core.proposal_digest !== proposal.content_digest || core.preparation_digest !== proposal.preparation_digest || core.manifest_digest !== proposal.prepared_manifest_digest || core.run_id !== proposal.run_id || core.step_id !== proposal.step_id || core.invocation_id !== proposal.invocation_id || core.action !== proposal.action || core.mapping_version !== subject.mapping_version || core.payload_digest !== subject.payload_digest || core.target_id !== head.owner_id || core.base_revision_id !== head.revision_id) return false;
  if (core.command !== (scope ? 'ricky.company.proposal.save-scope.v1' : 'ricky.company.proposal.save-estimate.v1') || core.canonical_command !== (scope ? 'commercial.proposal.revise' : 'estimate.calculate.v1') || core.target_doctype !== (scope ? 'Cipher Proposal' : 'Cipher Estimate') || core.saved_doctype !== (scope ? 'Cipher Proposal Revision' : 'Cipher Estimate Revision')) return false;
  if (core.core_digest !== await suggestionDigest(omit(core, ['core_digest'])) || core.receipt_id !== await suggestionDigest({ person, operation_id: core.operation_id }) || core.saved_revision_digest !== await suggestionDigest(saved.revision) || core.saved_revision_id !== saved.revision.id || saved.revision.company !== proposal.company || saved.revision.predecessor !== head.revision_id || saved.revision.author_person !== person) return false;
  if ('proposal' in saved) return scope && 'composition' in subject.payload && saved.proposal.id === head.owner_id && saved.proposal.company === proposal.company && saved.proposal.pursuit === proposal.source_manifest.pursuit.id && saved.proposal.current_revision === saved.revision.id && saved.revision.proposal === head.owner_id && saved.revision.revision_number === subject.payload.expected_revision + 1 && same(saved.revision.composition, subject.payload.composition);
  return !scope && 'lines' in subject.payload && companyRecord(saved.estimate, proposal.company) && companyRecord(saved.revision, proposal.company) && companyRecord(saved.calculation, proposal.company) && saved.estimate.id === head.owner_id && saved.estimate.pursuit_id === proposal.source_manifest.pursuit.id && saved.estimate.current_revision === saved.revision.id && saved.revision.estimate === head.owner_id && saved.calculation.id === saved.revision.calculation_snapshot && saved.calculation.subject_id === saved.revision.id && saved.calculation.estimate === head.owner_id && same(saved.calculation.inputs.lines, subject.payload.lines) && same(saved.calculation.inputs.adjustments, subject.payload.adjustments) && saved.calculation.inputs.basis_description === subject.payload.basis_description && same(saved.calculation.inputs.basis_citations.map(reference), subject.payload.basis_citations);
}

export async function matchesDraftSaveSubject(value: CompanyDraftSaveSubject, proposal: Suggestion, base: DraftSaveBase, user: string, person: string): Promise<boolean> {
  try {
    if (!publishedDraftSaveShape('CompanyDraftSaveSubject', value) || value.proposal_id !== proposal.id || value.proposal_version !== proposal.version || value.proposal_digest !== proposal.content_digest || value.action !== proposal.action || value.expires_at !== proposal.expires_at || value.payload_digest !== await suggestionDigest(value.payload) || value.eligible !== (value.reason === null) || Boolean(value.application) !== Boolean(value.saved) || value.application && value.eligible || !await matchesPayload(value, proposal, base)) return false;
    return !value.application || await matchesApplication(value.application, value.saved!, { proposal, subject: value, user, person });
  } catch { return false; }
}
export async function matchesDraftSaveResponse(value: CompanyDraftSaveResponse, input: CompanyDraftSaveRequest, binding: DraftSaveBinding): Promise<boolean> {
  try {
    return publishedDraftSaveShape('CompanyDraftSaveResponse', value) && input.company === binding.proposal.company && input.proposal_id === binding.proposal.id && input.expected_version === binding.proposal.version && input.expected_content_digest === binding.proposal.content_digest && input.mapping_version === binding.subject.mapping_version && input.expected_payload_digest === binding.subject.payload_digest && value.operation.id === input.operation_id && value.application.operation_id === input.operation_id && await matchesApplication(value.application, value.saved, binding);
  } catch { return false; }
}
