import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { compile } from 'json-schema-to-typescript';

const check = process.argv.includes('--check');

for (const [sourcePath, destination, title] of [
  ['api/schema.json', 'contracts.generated.ts', 'CipherApiEnvelope'],
  ['estimating/schemas/api-v1.schema.json', 'estimating.generated.ts', 'CipherEstimatingContract'],
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
