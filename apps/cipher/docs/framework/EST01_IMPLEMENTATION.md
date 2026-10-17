# EST-01 authored calculation

EST-01 persists authored unit conversions, rate sources, assembly revisions and draft estimate calculations in Frappe. It reuses native UOM, Currency, Item, Supplier and Customer masters. It does not implement calibrated takeoff, estimate acceptance, submission, award, baseline creation or ledger posting.

## Authority and sources

The `cipher_aec.estimating.api` RPC methods use the shared `cipher.api.v1` transport. Writes require the shared UUID idempotency key, current `estimate.write` and `estimate.read`, an open Project, and source access where consumed. Read methods require `estimate.read`; sourced records and receipts also recheck `document.read`, the original source bytes/checksums, and current native Item/party read permission and company association. Completed receipts retain their original calculated result; they confer no permanent source entitlement.

A site administrator qualifies an existing enabled native UOM with an immutable UUID, dimension, declared quantity precision and revision. Ordinary unqualified native UOM creation remains supported. Qualified identity, symbol, dimension, precision and whole-number semantics cannot be silently rewritten or renamed. Conversion records reference the exact source/target unit UUIDs and reduced rational factor, explicit source citation and authored permission assertion. Canonical validation comes from `migrations.validation`; names do not imply dimensional equivalence.

Rate sources preserve quote/date/expiry, geography, inclusions/exclusions, freight/tax assumptions, currency, exact decimal rate and precision, explicit source citation and permission assertion. Item/party links must be currently readable and associated with the exact company (or the exact Project Customer exception from the shared resolver). Recorded `permission_basis` is an authored assertion, not an inferred license entitlement.

Assembly and rate corrections create immutable successors. Assembly components pin their original rate revisions, work/resource quantities, material factor and waste. Labor and equipment require their respective typed time dimensions. Productivity and equipment duration come from the explicit work/resource quantity ratio.

## Exact calculation

Quantities and rates arrive as decimal strings. Every arithmetic intermediate uses an exact rational; binary floats, inferred dimensions, inconsistent conversion graphs, currency mismatches, expired rates and unsupported policies are refused. Native Currency `fraction_units` supplies the monetary exponent; unconfigured policy is refused.

Policy `cipher.estimate.line-half-up.v1` rounds each authored top-level line once using exact integer half-up arithmetic. Components receive a nonnegative largest-remainder allocation tied by stable component ID. Header direct cost sums included rounded lines; excluded alternates remain separately priced. Explicit indirect and contingency adjustments use authored fixed values or fractions of rounded direct cost and round separately.

A calculation transaction writes its immutable input/output snapshot, revision, stable-ID authored/calculated lines and draft estimate pointer together. It binds exact rate, assembly, conversion, unit, currency-policy and citation manifests plus input/output digests. Client totals are refused. New quotes never reprice existing snapshots automatically.

Shared command locking precedes estimate/source record locks. Effects acquire shared UOMs in sorted order, then Currency if needed, then sorted native Item/party references. Receipt authorization uses current locking reads without revisiting mutable lifecycle/latest-revision constraints.

## Contracts and verification

The machine-readable contract is `platform/apps/cipher_aec/cipher_aec/estimating/schemas/api-v1.schema.json`. It defines all nine requests, authored inputs, exact outputs, citations, manifests and the qualified-unit response. Currency selection remains explicit; no catalog/default is invented.

Local evidence is `evidence/r1/est01-acceptance.json`, with persisted request/response samples in `evidence/r1/est01-schema-samples.json`. The source hashes bind the tested implementation. Evidence covers exact known totals and conversion examples, high-precision native storage, invalid dimensions, immutable lineage, shared receipt replay/conflict, generic write refusal, source revocation, readable foreign-company native references, native permission revocation, and current replay authorization under an old MariaDB snapshot. The concurrent proof changes native Item company association; native role-permission revocation is a separate sequential proof.

This qualification uses explicitly authored synthetic documents and quotes with real Frappe/MariaDB persistence. It qualifies no live quote provider, model, source license entitlement, calibrated geometry or estimate acceptance workflow.
