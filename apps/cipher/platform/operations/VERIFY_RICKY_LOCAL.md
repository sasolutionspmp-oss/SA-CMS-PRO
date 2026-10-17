# Actual local Ricky HTTP verification

`verify_ricky_local.py` is an opt-in verifier for the existing synthetic trial
site and actual queued Ollama adapter. It does not initialize a site, start a
worker, register a fixture model, upload a source, grant a duty or directly touch
the database. Root holds the serialized native writer lease for execution.

Prerequisites are the reviewed Ollama candidate installed by root, the closed
`cipher_ricky_connection`/`cipher_ricky_ollama_endpoints` profile from
`cipher_aec/ricky/OLLAMA_HANDOFF.md`, and actual queued worker processing. Primary
requires current Project `project.read`, `ricky.run`, `document.read` and
`task.create` duties and native Task permission. Alias must remain a different
login for the same canonical person; outsider remains outside the target Project.
The existing nonsecret `cipher-local-trial-v1.json` manifest pins the source and
four users. Passwords come only from `CIPHER_TRIAL_PRIMARY_PASSWORD`,
`CIPHER_TRIAL_ALIAS_PASSWORD`, `CIPHER_TRIAL_REVIEWER_PASSWORD`,
`CIPHER_TRIAL_OUTSIDER_PASSWORD`, or the existing private
`CIPHER_FIXTURE_PASSWORD` environment. Never print their values.

Root must include the narrow Task-intent retrieval fix in `ricky/engine.py`.
`What is trial labor rate?` searches the literal topic `trial labor rate`.
`Please propose a Task to review the trial labor rate.` strips only its known
leading Task imperative before the same literal search. The full original
question still reaches the model. Ordinary source questions, middle command
words and anchorless restrictions remain unchanged. This is a lexical
convenience, not semantic retrieval. The verifier preflights both actual search
responses against the exact pinned citation and refuses to start a model run if
the source cannot be retrieved. The fixture is not padded with command words.

Run from the repository root, using actual operator-selected local paths:

```powershell
python apps/cipher/platform/operations/verify_ricky_local.py --fixture <nonsecret-seed-manifest.json> --base-url http://127.0.0.1:18890 --host-header cipher.localhost --output <new-ricky-http-report.json> --phase prepare
```

`prepare` authenticates actual cookie sessions, checks connection identity and
source bytes, starts one answer-only run and then one separate Task-proposal run,
polls their original IDs, verifies exact citations/model identity and persisted
worker steps, and records the exact proposal packet. The known rate question also
checks that the answer contains the numerical rate in the actual source. This
phase creates no Task. Root can inspect the saved packet, then save that exact
reversible Task draft as the authorized original login:

```powershell
python apps/cipher/platform/operations/verify_ricky_local.py --fixture <same-manifest.json> --base-url http://127.0.0.1:18890 --host-header cipher.localhost --output <same-ricky-http-report.json> --phase save
```

For an explicitly supervised single execution, `--phase journey` performs both
preparation and saving. No approval grant, posting or consequential authorization
route is called. The save uses `ricky.api.commit_proposal`, which invokes the
ordinary Task service. The verifier first proves the alias login cannot use the
original requesting login's proposal, saves as the original user, retries the
identical operation and checks exactly one additional native Task with identical
fields and its durable proposal receipt. Alias/outsider private reads are denied.

Every POST UUID and exact payload is atomically journaled to
`<report>.state.json` before transmission. An uncertain result retains `intent`;
`--resume` repeats that exact command/UUID or continues polling its original run.
Returned commands are not repeated except the explicit same-operation save
retry. The original fixture digest, HTTP origin, Host and questions must match.
Do not delete the journal, generate new operation IDs, change a timed-out
question, replace the adapter with a fixture, or start replacement runs to obtain
a green report. Provider failure/expired session/source/authority is an honest
failure requiring root reconciliation. Original session authority must remain
valid until pending work and Task saving finish; login does not fabricate it.

After root restarts the actual runtime, execute readback against the same state:

```powershell
python apps/cipher/platform/operations/verify_ricky_local.py --fixture <same-manifest.json> --base-url http://127.0.0.1:18890 --host-header cipher.localhost --output <same-ricky-http-report.json> --phase readback
```

Readback authenticates and reads only. It checks the same persisted answer,
model/citations, proposal packet, Task fields and native effect receipt. Keep this
isolated synthetic Project free of other Task writes until readback, because the
verifier checks its before/after Task ID difference is exactly the one saved Task.
An optional GET-only `--phase authority-denial` is available after root separately
revokes a relevant original-person duty; it verifies denial of original run and
proposal reads. Root owns that native change and restoration. The script never
grants, revokes or invents authority.

HTTP responses are capped at 512 KiB with a 15-second socket/wall limit,
environment proxies and redirects are disabled, Task listing is bounded to 20
pages, polling defaults to 330 seconds with at most 180 polls, and each report and
journal is capped at 2 MiB. Login bodies, passwords, cookies and CSRF tokens are
not included in evidence. Reports retain safe request IDs and exact synthetic
model/source/Task evidence.

The current public run readback exposes model identity/profile/prompt but omits
durable sampling. The report explicitly marks `sampling_readback` as requiring
root's separate native read audit; it never fills in guessed values. Root must
reconcile the actual stored run `sampling`, model digest and source manifest
before claiming the combined journey qualified. HTTP evidence alone does not
qualify concurrency capacity, full context, provider cancellation, training
lineage, CAD, finance, production or external delivery.

Prepared-source verification (no model/site execution):

```powershell
python -m unittest discover -s apps/cipher/platform/operations/tests -p test_ricky_local_verifier.py
$env:PYTHONPATH='apps/cipher/platform/apps/cipher_aec'
python -m unittest cipher_aec.tests.test_ricky_intent cipher_aec.tests.test_ricky
```

The 16 verifier tests use explicit test responses and real loopback HTTP stubs.
The five intent tests were observed failing against the original function before
the fix, then passed with all 27 existing orchestration tests. These are source
contract checks; no actual native journey was executed by the preparation lane.
