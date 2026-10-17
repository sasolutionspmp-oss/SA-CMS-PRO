type Shape = Record<string, unknown>;
const object = (v: unknown): v is Shape => Boolean(v && typeof v === 'object' && !Array.isArray(v));
export function sameValue(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => sameValue(v, b[i]));
  return object(a) && object(b) && Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(k => Object.hasOwn(b, k) && sameValue(a[k], b[k]));
}
const keywords = new Set(['$ref', '$comment', 'description', 'title', 'type', 'properties', 'required', 'additionalProperties', 'items', 'minItems', 'maxItems', 'minLength', 'maxLength', 'minimum', 'maximum', 'maxProperties', 'format', 'pattern', 'enum', 'const', 'oneOf', 'anyOf']);
const type = (v: unknown, t: string) => t === 'null' ? v === null : t === 'object' ? object(v) : t === 'array' ? Array.isArray(v) : t === 'integer' ? Number.isSafeInteger(v) : t === 'number' ? typeof v === 'number' && Number.isFinite(v) : ['string', 'boolean'].includes(t) && typeof v === t;
// Finite evaluator over the unchanged published contracts; unknown constraints
// fail closed. It checks wire shape, never current source eligibility/authority.
function shape(v: unknown, s: Shape, defs: Record<string, Shape>, depth = 0): boolean {
  if (depth > 64 || Object.keys(s).some(k => !keywords.has(k))) return false;
  if (s.$ref) { const name = String(s.$ref).replace(/^#\/\$defs\//, ''); if (!defs[name] || !shape(v, defs[name], defs, depth + 1)) return false; }
  if (s.type && !(Array.isArray(s.type) ? s.type : [s.type]).some(t => type(v, String(t)))) return false;
  if (s.oneOf && (s.oneOf as Shape[]).filter(b => shape(v, b, defs, depth + 1)).length !== 1 || s.anyOf && !(s.anyOf as Shape[]).some(b => shape(v, b, defs, depth + 1))) return false;
  if (Object.hasOwn(s, 'const') && !sameValue(v, s.const) || s.enum && !(s.enum as unknown[]).some(e => sameValue(v, e))) return false;
  if (object(v)) {
    if (typeof s.maxProperties === 'number' && Object.keys(v).length > s.maxProperties) return false;
    const props = (s.properties || {}) as Record<string, Shape>;
    if ((s.required as string[] || []).some(k => !Object.hasOwn(v, k))) return false;
    for (const [k, item] of Object.entries(v)) {
      if (Object.hasOwn(props, k)) { if (!shape(item, props[k], defs, depth + 1)) return false; }
      else if (s.additionalProperties === false || object(s.additionalProperties) && !shape(item, s.additionalProperties, defs, depth + 1)) return false;
    }
  }
  if (Array.isArray(v) && (typeof s.minItems === 'number' && v.length < s.minItems || typeof s.maxItems === 'number' && v.length > s.maxItems || object(s.items) && !v.every(item => shape(item, s.items as Shape, defs, depth + 1)))) return false;
  if (typeof v === 'string') {
    if (typeof s.minLength === 'number' && [...v].length < s.minLength || typeof s.maxLength === 'number' && [...v].length > s.maxLength || s.pattern && !new RegExp(String(s.pattern)).test(v)) return false;
    if (s.format === 'uuid' && !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(v)) return false;
    if (s.format === 'date-time' && (!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(v) || !Number.isFinite(Date.parse(v)))) return false;
    if (s.format === 'date' && (!/^\d{4}-\d{2}-\d{2}$/.test(v) || !Number.isFinite(Date.parse(v + 'T00:00:00Z')) || new Date(v + 'T00:00:00Z').toISOString().slice(0, 10) !== v)) return false;
    if (s.format && !['uuid', 'date-time', 'date'].includes(String(s.format))) return false;
  }
  return !(typeof v === 'number' && (typeof s.minimum === 'number' && v < s.minimum || typeof s.maximum === 'number' && v > s.maximum));
}
export function schemaShape(schema: { $defs: unknown }, name: string, value: unknown): boolean {
  const defs = schema.$defs as Record<string, Shape>;
  return Boolean(defs[name] && shape(value, defs[name], defs));
}
