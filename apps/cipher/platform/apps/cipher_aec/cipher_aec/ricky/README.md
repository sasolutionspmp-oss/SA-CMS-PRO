# Embedded Ricky, R0

This module implements the existing-model adapter boundary, a closed typed tool registry, Frappe-persisted orchestration, source-bound proposals and the same Task command used by the manual form. It imports no legacy Cipher or Odoo code.

The existing local model's native Ollama serving contract has been recovered and implemented as the reviewed `ollama-local-v1` adapter. Host-only live checks verified the existing `ricky-v9:latest` identity, native tool response and constrained cited JSON answer on October 17, 2026. [Operator handoff](OLLAMA_HANDOFF.md) records the exact contract and configuration. The default remains unavailable until an operator configures the named endpoint. There is no runtime model simulator, guessed endpoint, OpenAI-compatible default, cloud fallback or embedding model. Explicit synthetic model fixtures remain test-only.

`adapter.ConnectionProfile` binds an explicit adapter kind, endpoint/secret references, model selection and bounded timeouts. Register a reviewed adapter implementation with `register_adapter`; configuration cannot import a Python path or load executable code. The built-in Ollama adapter resolves a closed operator endpoint record, pins model name/digest before and after inference, disables proxies/redirects, validates normalized answers/tool requests and enforces socket and wall deadlines. Capability status distinguishes provider reports from observed responses. The recovered unauthenticated local contract rejects a secret reference. No provider cancellation or full context/concurrency qualification is claimed.

`engine.RickyService` stores canonical Cipher Ricky Run/Step, Tool Invocation, Proposed Change, Delegation and Run Artifact records. `storage.FrappeStore` is the runtime repository. Redis enqueueing is a hint; `worker.recover_pending` rediscovers pending or expired-lease work from MariaDB. Worker checkpoints release transactions before inference. Lease/fencing tokens reject late results, and source/authority/session checks repeat at resume and each effect boundary. The default policy allows one active request per person, 32 site requests, eight tools, two retrieval rounds and a five-minute interactive budget. Model response rounds are also bounded.

The reviewed tools are `project.lookup`, `document.search` and `task.propose`. Closed schemas reject actor/company/project overrides, SQL, shell, dynamic Python, arbitrary paths and remote URLs. Source text is untrusted data. Citation IDs bind revision/page/excerpt hash; current document access and exact source hashes are rechecked before context, answer delivery and Task save. A proposal binds exact fields, source manifest, authority, version, digest and expiry. Saving requires the requesting user's authenticated session and the ordinary `projects.service.create_task` command. There is no model approval or Task-commit tool.

The API methods in `ricky.api` use the shared `cipher.api.v1` envelope: `connection_status`, `start_run`, `get_run`, `run_events`, `cancel_run`, `get_proposal`, `commit_proposal`. Start/cancel use shared command receipts and the canonical-person operation namespace. Proposal save delegates its operation ID to the Task command. Generic resource writes to durable Ricky records are refused by controllers. Cancellation fences future work and pending proposal application; existing Task receipts remain visible history.

Local verification:

```bash
PYTHONPATH=apps/cipher/platform/apps/cipher_aec python -m unittest discover \
  -s apps/cipher/platform/apps/cipher_aec/cipher_aec/tests -p 'test_ricky*.py'
```

The 27 unit tests verify typed contracts, prompt-injection tool refusal, citation provenance, source/identity/session revocation, proposal/version/expiry binding, Task replay, cancellation, resource ceilings, quarantine, lock ordering, transactional tool rollback and crash recovery.

The opt-in `cipher_aec.tests.test_ricky_acceptance.run_acceptance` bench function uses a dedicated synthetic user/project, real private source bytes and Frappe records with an explicitly injected test-only adapter. Actual container evidence records cited-answer persistence, Task save/replay, generic-write denial, rollback of a timed-out proposal handler and a separate-connection permission revocation under MariaDB REPEATABLE-READ. See `docs/framework/evidence/r0/ricky-transactional-acceptance.json` relative to the Cipher root. The fixture evidence does not qualify a live model. Host-only Ollama checks are recorded in `docs/framework/evidence/r3/ricky-local-ollama`; the actual native-app answer and Task journey is a separate qualification gate.
