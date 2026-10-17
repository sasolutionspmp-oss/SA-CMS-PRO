# COM-01 authored commercial drafts

The canonical native `Opportunity` and `Quotation` remain the commercial masters. Company-scoped `Cipher Pursuit` and `Cipher Proposal` sidecars link those masters uniquely. Immutable `Cipher Proposal Revision` records preserve authored plain-text sections, terms, qualified units, exact decimal inputs, selected alternates, and the persisted native quotation fingerprint. Section and price-line UUIDs survive reordering and native child-row replacement. No Customer, Item or pricing master is duplicated by a commercial command.

`commercial.api` exposes ten fixed company-scoped RPCs; exact closed request/response contracts are in [schemas/api-v1.schema.json](schemas/api-v1.schema.json). Create an authored pursuit for an explicit existing native Customer or Lead, then create a proposal and save successor revisions against the expected head and native fingerprint. Lists use actor/scope/duty-bound signed cursors and authorized counts. Current company duties and native party/source reads apply before detail, revision, comparison, history and receipt data. Generic linked native changes and custom revision mutations are guarded independently of HTTP routing.

Each composition declares a native selling `price_list` in the same company-base currency. This supplies ERPNext's required price-list/currency context; rates are explicitly authored manual decimal values, not inferred Item Price records. COM-01 supports conversion rate one, no tax, no discounts, and a declared half-up currency rounding policy. It runs the supported ERPNext controller, reads persisted decimal columns as SQL strings, and reconciles quantities, rates, amounts, units, alternates and totals before recording a revision. Unsupported native precision rolls the entire command back. The immutable revision binds the locked native Company base-currency/version policy and exact native Price List and Currency versions.

Pre-award drafts require no Project. Company document citations and estimate links currently return `company_reference_unavailable`; later work will extend the same canonical authorities. No placeholder Project, copied source storage, issue, send, award, Sales Order or financial posting is exposed here. Missing native fiscal-year policy returns a typed setup error; test qualification uses its own explicitly synthetic Company/calendar and never configures the main fixture's accounting policy.

Targeted verification:

```sh
PYTHONPATH=apps/cipher/platform/apps/cipher_aec python -m unittest cipher_aec.tests.test_commercial -q
bench --site cipher.localhost execute cipher_aec.tests.test_commercial_acceptance.run_acceptance
PYTHONPATH=apps/cipher/platform/apps/cipher_aec python -m cipher_aec.tests.test_commercial_http_acceptance
```

The native runner creates isolated explicit fixtures (or reuses its last fully committed fixture with `reuse_latest=1`). The HTTP runner uses that evidence's private fixture accounts and fresh process-only credentials, then restores its dedicated native-read grants and company duty. No credentials or session tokens are retained in evidence. Actual acceptance artifacts are under `docs/framework/evidence/r1/`; they do not qualify issue, distribution, external providers or production accounting policy.
