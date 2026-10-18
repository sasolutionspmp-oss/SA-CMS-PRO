import schema from '../../../platform/apps/cipher_aec/cipher_aec/quality_safety/schemas/api-v1.schema.json' with { type: 'json' };
import { sameValue } from './schema-validation';
type Shape = Record<string, unknown>;
const object = (value: unknown): value is Shape => Boolean(value && typeof value === 'object' && !Array.isArray(value) && [Object.prototype, null].includes(Object.getPrototypeOf(value)));
const validDay = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) && Number(value.slice(0, 4)) > 0 && Number.isFinite(Date.parse(value + 'T00:00:00Z')) && new Date(value + 'T00:00:00Z').toISOString().slice(0, 10) === value;
const keywords = new Set(['$ref', 'type', 'properties', 'required', 'additionalProperties', 'items', 'minItems', 'maxItems', 'minLength', 'maxLength', 'minimum', 'maximum', 'format', 'pattern', 'enum', 'const', 'oneOf', 'anyOf', 'allOf', 'not', 'if', 'then', 'else', 'uniqueItems', 'contentEncoding']);
const typed = (value: unknown, type: string) => type === 'null' ? value === null : type === 'object' ? object(value) : type === 'array' ? Array.isArray(value) : type === 'integer' ? Number.isSafeInteger(value) : type === 'number' ? typeof value === 'number' && Number.isFinite(value) : ['string', 'boolean'].includes(type) && typeof value === type;
// Finite evaluator for the published closed Quality & Safety contracts, including their
// conditional family/standing constraints. Authority remains server-owned.
function shape(value: unknown, rule: Shape, defs: Record<string, Shape>, depth = 0): boolean {
  const match = (child: Shape) => shape(value, child, defs, depth + 1);
  if (depth > 64 || Object.keys(rule).some(key => !keywords.has(key))) return false;
  if (rule.$ref && (!String(rule.$ref).startsWith('#/$defs/') || !defs[String(rule.$ref).slice(8)] || !match(defs[String(rule.$ref).slice(8)]))) return false;
  if (rule.type && !(Array.isArray(rule.type) ? rule.type : [rule.type]).some(type => typed(value, String(type)))) return false;
  if (rule.allOf && !(rule.allOf as Shape[]).every(match) || rule.anyOf && !(rule.anyOf as Shape[]).some(match) || rule.oneOf && (rule.oneOf as Shape[]).filter(match).length !== 1 || rule.not && match(rule.not as Shape)) return false;
  if (rule.if && !match((match(rule.if as Shape) ? rule.then : rule.else) as Shape || {})) return false;
  if (Object.hasOwn(rule, 'const') && !sameValue(value, rule.const) || rule.enum && !(rule.enum as unknown[]).some(item => sameValue(value, item))) return false;
  if (object(value)) {
    const properties = (rule.properties || {}) as Record<string, Shape>;
    if ((rule.required as string[] || []).some(key => !Object.hasOwn(value, key))) return false;
    for (const [key, item] of Object.entries(value)) {
      if (Object.hasOwn(properties, key)) { if (!shape(item, properties[key], defs, depth + 1)) return false; }
      else if (rule.additionalProperties === false || object(rule.additionalProperties) && !shape(item, rule.additionalProperties, defs, depth + 1)) return false;
    }
  }
  if (Array.isArray(value)) {
    if (Object.getPrototypeOf(value) !== Array.prototype || Object.keys(value).length !== value.length || Array.from({ length: value.length }, (_, i) => Object.hasOwn(value, i)).includes(false)) return false;
    if (typeof rule.minItems === 'number' && value.length < rule.minItems || typeof rule.maxItems === 'number' && value.length > rule.maxItems || object(rule.items) && !value.every(item => shape(item, rule.items as Shape, defs, depth + 1))) return false;
    if (rule.uniqueItems && value.some((item, index) => value.slice(0, index).some(prior => sameValue(item, prior)))) return false;
  }
  if (typeof value === 'string') {
    if (/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(value)) return false;
    if (rule.contentEncoding === 'base64' && (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value))) return false;
    if (typeof rule.minLength === 'number' && [...value].length < rule.minLength || typeof rule.maxLength === 'number' && [...value].length > rule.maxLength || rule.pattern && !new RegExp(String(rule.pattern)).test(value)) return false;
    if (rule.format === 'date-time' && (!/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value) || !Number.isFinite(Date.parse(value)) || !validDay(value.slice(0, 10)))) return false;
    if (rule.format === 'date' && !validDay(value)) return false;
    if (rule.format === 'uuid' && !/^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/.test(value)) return false;
    if (rule.format && !['uuid', 'date-time', 'date'].includes(String(rule.format))) return false;
  }
  return !(typeof value === 'number' && (typeof rule.minimum === 'number' && value < rule.minimum || typeof rule.maximum === 'number' && value > rule.maximum));
}
export function qualityShape(name: string, value: unknown) {
  const defs = schema.$defs as Record<string, Shape>;
  return Boolean(defs[name] && shape(value, defs[name], defs));
}
