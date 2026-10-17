import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { compile } from 'json-schema-to-typescript';

const check = process.argv.includes('--check');

for (const [sourcePath, destination, title] of [
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
  const source = await readFile(new URL(`../../platform/apps/cipher_aec/cipher_aec/${sourcePath}`, import.meta.url), 'utf8');
  let published = JSON.parse(source);
  const sourceTexts = [source];
  if (destination === 'company-draft-saves.generated.ts') {
    const available = { ...published.$defs };
    for (const dependency of ['commercial/schemas/api-v1.schema.json', 'estimating/schemas/api-v1.schema.json', 'estimating/schemas/api-company-v2.schema.json']) {
      const text = await readFile(new URL(`../../platform/apps/cipher_aec/cipher_aec/${dependency}`, import.meta.url), 'utf8');
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
    ...(['company-ricky-proposals.generated.ts', 'company-draft-saves.generated.ts'].includes(destination) ? { ignoreMinAndMaxItems: true } : {}),
    bannerComment: `/* Generated from cipher_aec/${sourcePath}. Do not edit.\n * Source SHA-256: ${hash}\n * Regenerate: npm run generate:api\n */`,
  });
  if (destination === 'company-ricky-proposals.generated.ts') generated += `\n// Published closed runtime shapes, generated from the same source as these types.\nexport const companyRickyProposalSchema = ${source.trim()} as const;\n`;
  if (destination === 'company-draft-saves.generated.ts') generated += `\n// Exact published definitions and their transitive canonical dependencies.\nexport const companyDraftSaveSchema = ${JSON.stringify(published, null, 2)} as const;\n`;
  const output = new URL(`../src/api/${destination}`, import.meta.url);
  if (check) {
    let existing = '';
    try { existing = await readFile(output, 'utf8'); } catch {}
    if (existing !== generated) { console.error(`Stale generated contract: src/api/${destination}. Run npm run generate:api.`); process.exitCode = 1; }
    else console.log(`Verified ${destination} (${hash.slice(0, 12)}).`);
  } else {
    await writeFile(output, generated);
    console.log(`Generated ${destination} (${hash.slice(0, 12)}).`);
  }
}
