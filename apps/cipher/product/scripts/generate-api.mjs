import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { compile } from 'json-schema-to-typescript';

const check = process.argv.includes('--check');
// Source digests bind canonical LF text bytes, preserving JSON order and content.
const canonicalText = value => value.replaceAll('\r\n', '\n');
const readCanonical = async path => canonicalText(await readFile(path, 'utf8'));

for (const [sourcePath, destination, title] of [
  ['field/schemas/api-v1.schema.json', 'field.generated.ts', 'CipherFieldContract'],
  ['document_control/schemas/api-v1.schema.json', 'document-control.generated.ts', 'CipherDocumentControlContract'],
  ['engineering/schemas/api-v1.schema.json', 'engineering.generated.ts', 'CipherEngineeringContract'],
  ['engineering_packages/schemas/api-v1.schema.json', 'engineering-packages.generated.ts', 'CipherEngineeringPackagesContract'],
  ['api/schema.json', 'contracts.generated.ts', 'CipherApiEnvelope'],
  ['estimating/schemas/api-v1.schema.json', 'estimating.generated.ts', 'CipherEstimatingContract'],
  ['commercial/schemas/api-v1.schema.json', 'commercial.generated.ts', 'CipherCommercialContract'],
  ['takeoff/schemas/api-v1.schema.json', 'takeoff.generated.ts', 'CipherTakeoffContract'],
  ['documents/schemas/company-api-v1.schema.json', 'company-documents.generated.ts', 'CipherCompanyDocumentContract'],
  ['estimating/schemas/api-company-v2.schema.json', 'company-estimating.generated.ts', 'CipherCompanyEstimatingContract'],
  ['integrations/schemas/distribution-v1.schema.json', 'distribution.generated.ts', 'CipherDistributionContract'],
  ['project_controls/schemas/api-v1.schema.json', 'project-controls.generated.ts', 'CipherProjectControlsContract'],
  ['awards/schemas/api-v1.schema.json', 'awards.generated.ts', 'CipherAwardContract'],
  ['takeoff/schemas/api-company-v2.schema.json', 'company-takeoff.generated.ts', 'CipherCompanyTakeoffContract'],
  ['ricky/schemas/company-api-v1.schema.json', 'company-ricky.generated.ts', 'CipherCompanyRickyContract'],
  ['ricky/schemas/company-proposal-api-v1.schema.json', 'company-ricky-proposals.generated.ts', 'CipherCompanyRickyProposalContract'],
  ['ricky/schemas/company-draft-save-api-v1.schema.json', 'company-draft-saves.generated.ts', 'CipherCompanyDraftSaveContract'],
]) {
  const source = await readCanonical(new URL(`../../platform/apps/cipher_aec/cipher_aec/${sourcePath}`, import.meta.url));
  let published = JSON.parse(source);
  const documentContracts = new Set();
  if (destination === 'document-control.generated.ts') {
    const reachable = new Set((published.anyOf || []).map(branch => branch.$ref));
    for (const manifest of ['route-contracts.json', 'company-route-contracts.json']) {
      const routes = JSON.parse(await readCanonical(new URL(`../../platform/apps/cipher_aec/cipher_aec/document_control/${manifest}`, import.meta.url)));
      for (const name of [...Object.values(routes.requests), ...Object.values(routes.responses)]) {
        if (!published.$defs?.[name] || !reachable.has(`#/$defs/${name}`)) throw new Error(`Document route contract is not reachable for generation: ${name}`);
        documentContracts.add(name);
      }
    }
  }
  const sourceTexts = [source];
  const fieldContracts = new Set();
  if (destination === 'field.generated.ts') {
    const routes = JSON.parse(await readCanonical(new URL('../../platform/apps/cipher_aec/cipher_aec/field/route-contracts.json', import.meta.url)));
    const reachable = new Set((published.anyOf || []).map(branch => branch.$ref));
    for (const name of [...Object.values(routes.requests), ...Object.values(routes.responses)]) {
      if (!published.$defs?.[name] || !reachable.has(`#/$defs/${name}`)) throw new Error(`Field route contract is not reachable for generation: ${name}`);
      fieldContracts.add(name);
    }
  }
  if (destination === 'company-draft-saves.generated.ts') {
    const available = { ...published.$defs };
    for (const dependency of ['commercial/schemas/api-v1.schema.json', 'estimating/schemas/api-v1.schema.json', 'estimating/schemas/api-company-v2.schema.json']) {
      const text = await readCanonical(new URL(`../../platform/apps/cipher_aec/cipher_aec/${dependency}`, import.meta.url));
      sourceTexts.push(text);
      for (const [name, definition] of Object.entries(JSON.parse(text).$defs)) {
        if (available[name] && JSON.stringify(available[name]) !== JSON.stringify(definition)) throw new Error(`Conflicting draft-save definition: ${name}`);
        available[name] = definition;
      }
    }
    const definitions = { ...published.$defs };
    const visit = value => {
      if (!value || typeof value !== 'object') return;
      if (value.$ref) {
        if (!value.$ref.startsWith('#/$defs/')) throw new Error('Draft-save contracts require an explicit local definition.');
        const name = value.$ref.slice('#/$defs/'.length);
        if (!available[name]) throw new Error(`Missing draft-save definition: ${name}`);
        if (!definitions[name]) { definitions[name] = available[name]; visit(definitions[name]); }
      }
      for (const child of Object.values(value)) visit(child);
    };
    for (const definition of Object.values(definitions)) visit(definition);
    published = { ...published, $defs: definitions };
  }
  const schema = JSON.parse(JSON.stringify(published).replaceAll('"$defs"', '"definitions"').replaceAll('#/$defs/', '#/definitions/'));
  if (destination === 'field.generated.ts') {
    // Runtime validates the unchanged original. Fold refinements for compiler
    // input so nonblank string constraints do not become object intersections.
    const typeShape = node => {
      if (!node || typeof node !== 'object') return;
      if (node.allOf && node.allOf.every(branch => !branch.$ref)) delete node.allOf;
      if (node.type === 'object' && node.oneOf) {
        const { oneOf, ...base } = node;
        node.oneOf = oneOf.map(branch => ({ ...base, ...branch,
          properties: Object.fromEntries(Object.entries({ ...base.properties, ...branch.properties }).map(([key, value]) => [key, value.$ref || value.allOf ? value : { ...(base.properties?.[key] || {}), ...value }])),
          required: [...new Set([...(base.required || []), ...(branch.required || [])])], additionalProperties: false }));
        for (const key of Object.keys(base)) delete node[key];
      }
      for (const child of Object.values(node)) {
        if (Array.isArray(child)) child.forEach(typeShape); else typeShape(child);
      }
    };
    typeShape(schema);
  }
  if (destination === 'company-ricky-proposals.generated.ts') {
    // The compiler otherwise drops siblings of this oneOf. Merge equivalent
    // closed branches for types only; runtime validation uses the original.
    const { oneOf, ...base } = schema.definitions.CompanyRickyProposalResponse;
    schema.definitions.CompanyRickyProposalResponse = { oneOf: oneOf.map(branch => ({ ...base, ...branch,
      properties: { ...base.properties, ...branch.properties }, required: [...new Set([...base.required, ...branch.required])], additionalProperties: false })) };
  }
  const hash = createHash('sha256').update(sourceTexts.length === 1 ? source : JSON.stringify(sourceTexts)).digest('hex');
  let generated = await compile(schema, title, {
    unreachableDefinitions: true,
    ...(['company-ricky-proposals.generated.ts', 'company-draft-saves.generated.ts', 'engineering-packages.generated.ts', 'document-control.generated.ts', 'field.generated.ts'].includes(destination) ? { ignoreMinAndMaxItems: true } : {}),
    bannerComment: `/* Generated from cipher_aec/${sourcePath}. Do not edit.\n * Source SHA-256: ${hash}\n * Regenerate: npm run generate:api\n */`,
  });
  for (const name of documentContracts) {
    if (!generated.includes(`export interface ${name} `) && !generated.includes(`export type ${name} `)) throw new Error(`Document route contract was not exported: ${name}`);
  }
  for (const name of fieldContracts) {
    if (!generated.includes(`export interface ${name} `) && !generated.includes(`export type ${name} `)) throw new Error(`Field route contract was not exported: ${name}`);
  }
  if (destination === 'company-ricky-proposals.generated.ts') generated += `\n// Published closed runtime shapes, generated from the same source as these types.\nexport const companyRickyProposalSchema = ${source.trim()} as const;\n`;
  if (destination === 'company-draft-saves.generated.ts') generated += `\n// Exact published definitions and their transitive canonical dependencies.\nexport const companyDraftSaveSchema = ${JSON.stringify(published, null, 2)} as const;\n`;
  const output = new URL(`../src/api/${destination}`, import.meta.url);
  if (check) {
    let existing = '';
    try { existing = await readCanonical(output); } catch {}
    if (existing !== generated) { console.error(`Stale generated contract: src/api/${destination}. Run npm run generate:api.`); process.exitCode = 1; }
    else console.log(`Verified ${destination} (${hash.slice(0, 12)}).`);
  } else {
    await writeFile(output, generated);
    console.log(`Generated ${destination} (${hash.slice(0, 12)}).`);
  }
}
