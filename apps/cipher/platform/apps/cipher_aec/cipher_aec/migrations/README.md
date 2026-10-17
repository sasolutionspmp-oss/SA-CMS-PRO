# Independent canonical data contracts: MIG-01

R0 implements a versioned, read-only format for master records, dimension definitions and exact quantities. ERPNext remains the authoritative source of Company, Project, Customer, Supplier, Item, UOM and Cost Center records. There is no second customer/item/project master, source-specific importer, applied import, cutover or persistent external-reference mapping in this module.

`schemas/canonical-v1.schema.json` publishes the structural JSON Schema. `validation.py` adds referential, scope and exact-unit checks. `fixtures/canonical-masters-v1.json` is a fresh standalone synthetic dataset with 21 company/project/customer/supplier/item/unit/cost-center/cost-code/cost-type/dimension records. It requires no existing ERP database or historical source format to validate.

## Format and identity

The envelope is `cipher.canonical.v1`, with a dataset UUID, explicit company/project scope, records, unit conversions and optional quantity examples. Each record has an immutable UUID, entity kind, positive revision and whitelisted fields. A native binding is explicitly `{doctype, name, version?}`. Source UUIDs remain distinct from display labels and canonical Frappe identifiers. The exporter requires explicit UUID bindings and never guesses matches from names. It does not claim a persistent identity mapping across separate requests or sites. Registered ERPNext UOM metadata, when present, supplies and enforces the immutable unit UUID and revision.

No arbitrary DocType, native field selection, SQL filter, path, URL or script is accepted. Two source UUIDs cannot bind one target in a manifest. Business codes and source identities are unique within their declared kind/company. Unknown references, wrong reference kinds, company mixing, duplicate JSON keys, cycles and unsupported fields are rejected. A company's unconfigured time zone is explicit `null` with a setup requirement; it is never replaced with an assumed company policy.

## Exact units

Quantities are decimal strings with declared UOM precision. Unit definitions explicitly distinguish length, area, volume, mass, count, time, labor time and equipment time. No dimension is inferred from a native UOM name. Conversion factors are reduced positive rational integer strings with their own UUID, revision and required source reference. Conversion paths must agree exactly; incompatible dimensions, conflicting cycles, zero/float factors and resource-excessive rational paths are refused. Quantity previews return exact numerator/denominator values and never silently round.

`estimating` owns persisted `Cipher Unit Conversion` authority and registered native UOM metadata. These interchange records and validators do not create a competing unit master. Unregistered native UOM export requires explicit operator dimension/precision declarations and returns a warning; that declaration is not standards verification.

## Read-only API

Authenticated same-origin POST RPCs are:

- `cipher_aec.migrations.api.validate_manifest(company, project, manifest)` validates caller data without checking target existence.
- `cipher_aec.migrations.api.preview_manifest(company, project, manifest)` reports matches, stale targets, field changes or unbound create candidates. A missing, denied or wrong-scope target has the same `unavailable` result.
- `cipher_aec.migrations.api.export_records(company, project, dataset_id, references, unit_conversions?, quantities?)` exports explicit native targets. References contain `{id, kind, name}` and optional UOM `{unit_definition: {dimension, precision}}`.

All three use the shared `cipher.api.v1` response envelope. They require current project scope; each preview target additionally requires native Frappe read permission, and every exported target requires both native read and export permission and a proven company/project association. Global Customer/Supplier/Item records without a supported company/project association are unavailable. Export is all-or-nothing; it never returns partial private target information. Only whitelisted fields enter a preview or export. Unregistered UOM previews remain declaration candidates with warnings; registered UOM previews verify immutable UUID/revision and refuse incompatible metadata. Native Project status values include `On hold`, as defined by the pinned ERPNext schema. Preview/export perform zero business database writes and always return `apply_available: false`. Actual business-data onboarding remains MIG-02 (R4).

## Verification

```sh
PYTHONPATH=apps/cipher/platform/apps/cipher_aec python -m unittest cipher_aec.tests.test_migrations -v
bench --site cipher.localhost execute cipher_aec.tests.test_migrations_acceptance.run_acceptance
```

The 18 independent contract tests cover identity/ref/cycle/precision failures, exact rational paths and incompatible dimensions, deterministic digests, stale targets, unavailable-target opacity, qualified/unqualified unit authority, native `On hold` status, and explicit unset policy. The published schema and standalone fixture were also checked using a Draft 2020-12 validator.

Actual Frappe/ERPNext/MariaDB acceptance creates isolated, clearly labeled native master fixtures and a separate project. It verifies nine real exported native records across seven supported kinds, reordered identity stability, native-field roundtrip preview with explicit unregistered-unit declaration status, exact 12-to-1 conversion, current native read/export permissions, identical private/missing target results and zero export/preview writes. See `docs/framework/evidence/r0/migration-acceptance.json`. Native schema/runtime integration is qualified; external source import and applied migration are not enabled.

HTTP qualification uses the existing isolated native fixture, a private cookie session and its own temporary role grants. Run the host test from the repository root with `PYTHONPATH=apps/cipher/platform/apps/cipher_aec python -m cipher_aec.tests.test_migrations_http_acceptance`. The runner uses standard-library HTTP/cookies and the JSON Schema test validator. It checks all three live routes, missing CSRF, native Export denial/grant/revocation in the same session, source-duty revocation, private-target opacity and selected source-version stability. It records no credentials or CSRF/cookie values. See `docs/framework/evidence/r0/migration-http-acceptance.json`.
