# Embedded Ricky, R0

This module implements the existing-model adapter boundary, a closed typed tool registry, Frappe-persisted orchestration, source-bound proposals and the same Task command used by the manual form. It imports no legacy Cipher or Odoo code.

The existing local model connection is **unavailable until its actual serving contract is provided**. The shipped runtime has no model simulator, guessed endpoint, OpenAI-compatible default, cloud fallback, embedding model or synthetic response. Explicit model fixtures exist only in `tests/test_ricky.py`.

`adapter.ConnectionProfile` binds an explicit adapter kind, endpoint/secret references, model selection and bounded timeouts. Register a reviewed adapter implementation with `register_adapter`; configuration cannot import a Python path or load executable code. An adapter returns normalized `ModelResponse` records and confirmed capability status. Protocol, authentication, health, model selection and capabilities still require the real model handoff and live qualification.

`engine.RickyService` stores canonical Cipher Ricky Run/Step, Tool Invocation, Proposed Change, Delegation and Run Artifact records. `storage.FrappeStore` is the runtime repository. Redis enqueueing is a hint; `worker.recover_pending` rediscovers pending or expired-lease work from MariaDB. Worker checkpoints release transactions before inference. Lease/fencing tokens reject late results, and source/authority/session checks repeat at resume and each effect boundary. The default policy allows one active request per person, 32 site requests, eight tools, two retrieval rounds and a five-minute interactive budget. Model response rounds are also bounded.

The reviewed tools are `project.lookup`, `document.search` and `task.propose`. Closed schemas reject actor/company/project overrides, SQL, shell, dynamic Python, arbitrary paths and remote URLs. Source text is untrusted data. Citation IDs bind revision/page/excerpt hash; current document access and exact source hashes are rechecked before context, answer delivery and Task save. A proposal binds exact fields, source manifest, authority, version, digest and expiry. Saving requires the requesting user's authenticated session and the ordinary `projects.service.create_task` command. There is no model approval or Task-commit tool.

The API methods in `ricky.api` use the shared `cipher.api.v1` envelope: `connection_status`, `start_run`, `get_run`, `run_events`, `cancel_run`, `get_proposal`, `commit_proposal`. Start/cancel use shared command receipts and the canonical-person operation namespace. Proposal save delegates its operation ID to the Task command. Generic resource writes to durable Ricky records are refused by controllers. Cancellation fences future work and pending proposal application; existing Task receipts remain visible history.

Local verification:

```bash
PYTHONPATH=apps/cipher/platform/apps/cipher_aec python -m unittest discover \
  -s apps/cipher/platform/apps/cipher_aec/cipher_aec/tests -p 'test_ricky*.py'
```

The 27 unit tests verify typed contracts, prompt-injection tool refusal, citation provenance, source/identity/session revocation, proposal/version/expiry binding, Task replay, cancellation, resource ceilings, quarantine, lock ordering, transactional tool rollback and crash recovery.

The opt-in `cipher_aec.tests.test_ricky_acceptance.run_acceptance` bench function uses a dedicated synthetic user/project, real private source bytes and Frappe records with an explicitly injected test-only adapter. Actual container evidence records cited-answer persistence, Task save/replay, generic-write denial, rollback of a timed-out proposal handler and a separate-connection permission revocation under MariaDB REPEATABLE-READ. See `docs/framework/evidence/r0/ricky-transactional-acceptance.json` relative to the Cipher root. The actual local-model connection remains unqualified; this fixture evidence does not qualify a live model.
