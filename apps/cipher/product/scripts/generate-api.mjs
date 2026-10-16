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
]) {
  const source = await readFile(new URL(`../../platform/apps/cipher_aec/cipher_aec/${sourcePath}`, import.meta.url), 'utf8');
  const schema = JSON.parse(source.replaceAll('"$defs"', '"definitions"').replaceAll('#/$defs/', '#/definitions/'));
  const hash = createHash('sha256').update(source).digest('hex');
  const generated = await compile(schema, title, {
    unreachableDefinitions: true,
    bannerComment: `/* Generated from cipher_aec/${sourcePath}. Do not edit.\n * Source SHA-256: ${hash}\n * Regenerate: npm run generate:api\n */`,
  });
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
