import { readFile, writeFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { compile } from 'json-schema-to-typescript';

// Owned FLD-02 generation fragment. The shared generator is unchanged.
const canonical = value => value.replaceAll('\r\n', '\n');
const schemaPath = '../../platform/apps/cipher_aec/cipher_aec/field_offline/schemas/api-v1.schema.json';
const routePath = '../../platform/apps/cipher_aec/cipher_aec/field_offline/route-contracts.json';
const source = canonical(await readFile(new URL(schemaPath, import.meta.url), 'utf8'));
const routeSource = canonical(await readFile(new URL(routePath, import.meta.url), 'utf8'));
const published = JSON.parse(source), routes = JSON.parse(routeSource);
const expected = ['register_device', 'revoke_device', 'stage_capture', 'get_capture', 'inspect_capture', 'apply_capture', 'discard_capture', 'resolve_capture'];
for (const group of ['requests', 'responses']) {
  if (Object.keys(routes[group]).sort().join() !== [...expected].sort().join()) throw new Error(`Offline ${group} must declare the exact eight owned routes.`);
}
const reachable = new Set(published.anyOf.map(branch => branch.$ref));
const names = new Set([...Object.values(routes.requests), ...Object.values(routes.responses)]);
for (const name of names) if (!published.$defs[name] || !reachable.has(`#/$defs/${name}`)) throw new Error(`Unreachable offline route contract: ${name}`);
const schema = JSON.parse(JSON.stringify(published).replaceAll('"$defs"', '"definitions"').replaceAll('#/$defs/', '#/definitions/'));
// Fold refinements only in compiler input. Runtime consumes the original schema.
function typeShape(node) {
  if (!node || typeof node !== 'object') return;
  if (node.allOf && node.allOf.every(branch => !branch.$ref)) delete node.allOf;
  if (node.type === 'object' && node.oneOf) {
    const { oneOf, ...base } = node;
    node.oneOf = oneOf.map(branch => ({ ...base, ...branch,
      properties: Object.fromEntries(Object.entries({ ...base.properties, ...branch.properties }).map(([key, value]) => [key, value.$ref || value.allOf ? value : { ...(base.properties?.[key] || {}), ...value }])),
      required: [...new Set([...(base.required || []), ...(branch.required || [])])], additionalProperties: false }));
    for (const key of Object.keys(base)) delete node[key];
  }
  for (const child of Object.values(node)) if (Array.isArray(child)) child.forEach(typeShape); else typeShape(child);
}
typeShape(schema);
const hash = text => createHash('sha256').update(text).digest('hex');
const generated = await compile(schema, 'CipherFieldOfflineContract', {
  unreachableDefinitions: true, ignoreMinAndMaxItems: true,
  bannerComment: `/* Generated from cipher_aec/field_offline/schemas/api-v1.schema.json. Do not edit.\n * Source SHA-256: ${hash(source)}\n * Route manifest SHA-256: ${hash(routeSource)}\n * Regenerate: node scripts/generate-field-offline-api.mjs\n */`,
});
for (const name of names) if (!generated.includes(`export interface ${name} `) && !generated.includes(`export type ${name} `)) throw new Error(`Offline route type was not exported: ${name}`);
const output = new URL('../src/api/field-offline.generated.ts', import.meta.url);
if (process.argv.includes('--check')) {
  let existing = '';
  try { existing = canonical(await readFile(output, 'utf8')); } catch {}
  if (existing !== generated) { console.error('Stale field-offline.generated.ts; run node scripts/generate-field-offline-api.mjs.'); process.exitCode = 1; }
  else console.log(`Verified field-offline.generated.ts (${hash(source).slice(0, 12)}; eight routes).`);
} else {
  await writeFile(output, generated);
  console.log(`Generated field-offline.generated.ts (${hash(source).slice(0, 12)}; eight routes).`);
}
