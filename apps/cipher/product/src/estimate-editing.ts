import type { EstAdjustment, EstAssemblyDefinition, EstCitation, EstLineInput, EstRateDefinition, EstSnapshotRecord, EstUnitRecord } from './api/estimating.generated';
import type { CompanyEstSnapshotRecord } from './api/company-estimating.generated';

export interface EstimateDraft { lines: EstLineInput[]; adjustments: EstAdjustment[]; conversion_ids: string[]; basis_description: string; basis_citations: EstCitation[] }
export interface SourceChoice { id: string; kind: 'rate' | 'assembly'; label: string; unitId: string; rate?: EstRateDefinition; assembly?: EstAssemblyDefinition }
export const decimalPattern = /^(0|[1-9][0-9]*)(\.[0-9]{1,12})?$/;
export function exactDisplay(value: string) {
  const [integer, fraction] = value.split('.');
  return `${integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',')}${fraction === undefined ? '' : `.${fraction}`}`;
}
export function emptyLine(unit?: EstUnitRecord, source?: SourceChoice): EstLineInput {
  const base = { line_id: crypto.randomUUID(), description: '', quantity: { amount: '', unit_id: unit?.id ?? '', precision: unit?.fields.precision ?? 0 }, cost_code: '', notes: '', alternate: '', included: true };
  return source?.kind === 'assembly' ? { ...base, assembly_revision_id: source.id } : { ...base, rate_source_id: source?.id ?? '', material_factor: '1', waste_fraction: '0' };
}
export function selectLineSource(line: EstLineInput, source: SourceChoice): EstLineInput {
  const { line_id, description, quantity, cost_code, notes, alternate, included } = line;
  const base = { line_id, description, quantity, cost_code, notes, alternate, included };
  return source.kind === 'assembly' ? { ...base, assembly_revision_id: source.id } : { ...base, rate_source_id: source.id, material_factor: 'material_factor' in line ? line.material_factor : '1', waste_fraction: 'waste_fraction' in line ? line.waste_fraction : '0' };
}
export function validateDraft(draft: EstimateDraft, units: EstUnitRecord[], choices: SourceChoice[]) {
  const errors: Record<string, string> = {};
  if (!draft.lines.length || draft.lines.length > 100) errors.lines = 'Use 1–100 estimate lines.';
  if (!draft.basis_description.trim()) errors.basis_description = 'Describe the basis of this authored estimate.';
  for (const [index, line] of draft.lines.entries()) {
    const key = `lines.${index}`;
    const unit = units.find(item => item.id === line.quantity.unit_id);
    if (!line.description.trim()) errors[`${key}.description`] = 'Enter a description.';
    if (!decimalPattern.test(line.quantity.amount) || line.quantity.amount.length > 43) errors[`${key}.quantity`] = 'Use an exact nonnegative decimal, without commas or exponent notation.';
    else if (unit && (line.quantity.amount.split('.')[1]?.length ?? 0) > unit.fields.precision) errors[`${key}.quantity`] = `This unit permits ${unit.fields.precision} decimal places.`;
    if (!unit) errors[`${key}.unit`] = 'Choose a qualified unit.';
    const sourceId = 'rate_source_id' in line ? line.rate_source_id : line.assembly_revision_id;
    if (!choices.some(source => source.id === sourceId)) errors[`${key}.source`] = 'Choose a current rate or assembly source.';
    if ('material_factor' in line) {
      if (!decimalPattern.test(line.material_factor) || !/[1-9]/.test(line.material_factor)) errors[`${key}.material_factor`] = 'Use an exact positive decimal.';
      if (!decimalPattern.test(line.waste_fraction)) errors[`${key}.waste_fraction`] = 'Use an exact nonnegative fraction; 0.05 means 5%.';
    }
  }
  draft.adjustments.forEach((adjustment, index) => {
    if (!decimalPattern.test(adjustment.value) || !adjustment.label.trim() || !adjustment.basis_description.trim()) errors[`adjustments.${index}`] = 'Each adjustment needs a label, an exact nonnegative value, and its basis.';
  });
  return errors;
}
export function parsePastedLines(text: string, units: EstUnitRecord[], choices: SourceChoice[]) {
  const rows = text.trim().split(/\r?\n/).filter(row => row.trim());
  if (rows[0]?.split('\t')[0].toLowerCase() === 'description') rows.shift();
  if (!rows.length || rows.length > 100) throw new Error('Paste 1–100 tab-separated rows.');
  const lines = rows.map((row, index) => {
    const [description = '', amount = '', symbol = '', sourceToken = '', costCode = '', waste = '0', ...extra] = row.split('\t');
    if (extra.length) throw new Error(`Row ${index + 1}: use the six supported columns.`);
    const matches = units.filter(unit => unit.id === symbol || unit.fields.symbol === symbol || unit.target.name === symbol);
    if (matches.length !== 1) throw new Error(`Row ${index + 1}: choose one exact qualified unit name or ID.`);
    const sources = choices.filter(source => source.id === sourceToken || source.label === sourceToken || source.rate?.title === sourceToken || source.assembly?.title === sourceToken);
    if (sources.length !== 1) throw new Error(`Row ${index + 1}: choose one exact source title or ID.`);
    const line = { ...emptyLine(matches[0], sources[0]), description, cost_code: costCode, quantity: { amount, unit_id: matches[0].id, precision: matches[0].fields.precision } };
    return 'waste_fraction' in line ? { ...line, waste_fraction: waste } : line;
  });
  const errors = validateDraft({ lines, adjustments: [], conversion_ids: [], basis_description: 'Pasted authored quantities', basis_citations: [] }, units, choices);
  if (Object.keys(errors).length) throw new Error(Object.values(errors)[0]);
  return lines;
}
export function draftFromSnapshot(snapshot?: EstSnapshotRecord | CompanyEstSnapshotRecord): EstimateDraft {
  return snapshot ? structuredClone({ lines: snapshot.inputs.lines, adjustments: snapshot.inputs.adjustments, conversion_ids: snapshot.inputs.unit_manifest.unit_conversions.map(conversion => conversion.id), basis_description: snapshot.inputs.basis_description, basis_citations: snapshot.inputs.basis_citations }) : { lines: [], adjustments: [], conversion_ids: [], basis_description: '', basis_citations: [] };
}
