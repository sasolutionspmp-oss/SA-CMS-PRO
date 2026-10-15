import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { compile } from 'json-schema-to-typescript';

const schemaUrl = new URL('../../platform/apps/cipher_aec/cipher_aec/api/schema.json', import.meta.url);
const source = await readFile(schemaUrl, 'utf8');
// Normalize the standard 2020-12 $defs spelling for the TypeScript compiler.
const schema = JSON.parse(source.replaceAll('"$defs"', '"definitions"').replaceAll('#/$defs/', '#/definitions/'));
const hash = createHash('sha256').update(source).digest('hex');
const generated = await compile(schema, 'CipherApiEnvelope', {
  unreachableDefinitions: true,
  bannerComment: `/* Generated from cipher_aec/api/schema.json. Do not edit.\n * Source SHA-256: ${hash}\n * Regenerate: npm run generate:api\n */`,
});
await writeFile(new URL('../src/api/contracts.generated.ts', import.meta.url), generated);
console.log(`Generated API types from backend schema (${hash.slice(0, 12)}).`);
