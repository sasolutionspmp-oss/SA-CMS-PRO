# DOC03 reviewer revalidation: independent source finding

Exact reviewed source: `a3577803e09e72b9af22178bdd9c4d1225536485` on
`cipher/local-trial-20261017`, fetched into a separate sparse worktree. The source
worktree remained unchanged during diagnosis. FLD02, DOC03 and DOC04 published refs
are preserved. Cloud root had 18 MiB free, /tmp about176 MiB, cgroup memory about
14.4/16 GiB; only bounded /dev/shm source/host work was performed.

## Finding

The deterministic host fingerprint is **document_prelock_required (409)**,
converted by the broad reviewer-loop `except DomainError` in
`governance/approvals.py:484–488` into **reviewer_authority_revoked (403)**.
This source finding explains the reported native failure positions. It is not
an observation of the swallowed native exception itself; actual native proof
remains pending with the local owner.

The outer canonical execution command uses `document_context.prelock(actor)`
then `document_context.hold(actor)` with requester Morgan. `locking._active`
and generated-source `provenance._prelocked` are intentionally actor-bound.
The grant-consumption loop correctly obtains reviewer Jordan and checks current
Project `approval.decide`, then requests a **locking** documentary review as Jordan.

1. Company adoption: `domain_approvals.authorize` → documentary
   `authorize_subject` → `service.read` → `service._prelock` for the foreign Company
   origin → `DocumentContext.hold(Jordan)`. `locking.py:169` refuses Jordan's
   identity inside Morgan's active context. This occurs on the first shared
   adoption, matching native test line76.
2. Project distribution: documentary `_eligible('transmittal')` →
   `locking.recipient_read(... actor=Jordan, lock=True)`. `locking.py:246–247`
   requires the held context's identity to equal that actor. Morgan's context
   therefore refuses it. Earlier ordinary Project adoption/issue paths lack this
   exact crossing; distribution is the first such path, matching native line43.

These guards are correct protections. Removing actor equality, replacing the
requester context, borrowing the generated-source token or using nullcontext
would hide the defect by weakening the boundary.

## Why a global lock=False edit is insufficient

Fresh nonlocking review as Jordan passes the host positive controls without
changing either requester token. Current Company/Project/native permissions,
read/ingest/distribution rights and canonical-person independence still deny
their respective negative controls. This is a viable read pattern **only after
the complete independent reviewer authority has been prelocked**.

Current `DocumentContext.prelock` locks origin duties for the requester and
declared recipients. The Company adoption reviewer is not a recipient. Canonical
participant Person/Binding/User locks do not substitute for locking that Person's
Company/source duties: `governance/controllers.py:35–44` does not acquire target
Person locks when validating a duty update. A host control records that Morgan's
Company duty query is FOR UPDATE while Jordan's independent fresh Company query
is not. Simply changing the reviewer call to lock=False omits this protection.

The local fix should bind the exact reviewed packet/grant/reviewer to the complete
source union; prelock reviewer identities and relevant target/origin duty rows
before masters/source locks; then independently run canonical reviewer reads as
Jordan without replacing or borrowing Morgan's admission tokens. Keep the existing
Human, independent-person, current-scope/native permission, original source/rights,
recipient and changed-plan checks. Engineering has no equivalent actor-bound
Company-source context; its passing paths do not establish this case.

The local source agent owns that functional patch. This independent lane does
not claim a safe functional fix has been implemented or natively qualified.

## Evidence and external patch

`test_revalidation_host.py` imports actual current_actor/require_project/
require_company, DocumentContext.discover/prelock/hold, provenance.prelocked,
rights and documentary/domain review callbacks. The reviewer loop is compiled
directly from the pinned approval source. SQL/session/native permission/storage/
source adapters and issue lifecycle projection are explicit host doubles. No
nullcontext replaces the context under diagnosis. No command, approval effect,
award, runtime, database or provider is executed.

- `03-diagnostic-controls.log`: six controls passed. Both inner409→outer403
  paths, unchanged requester tokens, current permission/rights/independence denial
  and the missing nonrecipient reviewer Company-duty lock are demonstrated.
- `04-fail-first-regression.log`: two intended-success regressions fail on the
  pinned source with reviewer_authority_revoked, as required before the local fix.
  They remain deliberately red here; there is no functional-fix green claim.
- `DIAGNOSTIC_ONLY_UNMASK.patch`: external, unapplied, four-line diagnostic
  proposal. It propagates existing documentary/generated prelock409 errors instead
  of mislabeling them as revoked review authority. It does **not** make approval
  succeed, change lock mode, grant rights, consume an approval or fix admission.
- `06-diagnostic-patch-fixture-corrected.log`: one test with both source scenarios
  passes, proving the diagnostic patch preserves the inner denial and both owner
  tokens. The patch is applied to in-memory parsed reviewer-loop text only.

Initial logs are retained:01 lacked source adapter attributes during fixture
imports;02 corrected those fixtures and passed five initial controls.05 accidentally
placed one intended-red regression in the diagnostic class;06 corrects that test
grouping. None of those setup/grouping corrections changed application source.

Run from a selected source checkout (no Frappe runtime):

```sh
export CIPHER_DOC03_REVIEW_SOURCE="$PWD/apps/cipher/platform/apps/cipher_aec/cipher_aec"
export PYTHONPATH="$PWD/apps/cipher/platform/apps/cipher_aec"
PYTHONDONTWRITEBYTECODE=1 python /path/to/test_revalidation_host.py ReviewSourceTests -v
PYTHONDONTWRITEBYTECODE=1 python /path/to/test_revalidation_host.py IntendedBehaviorRegression -v
PYTHONDONTWRITEBYTECODE=1 python /path/to/test_revalidation_host.py DiagnosticPatchTests -v
```

The final command tests diagnostic unmasking only. For the local functional fix,
adapt/add the explicit reviewer-admission setup to the host regression and retain
the real context/provenance/permission logic; do not restore nullcontext fixtures.
Then qualify the exact actual native Project/Company paths and denied/recovery
cases locally. No cloud native retry was performed. The previous automatic award
rejection remains in force; no award route was retried and procurement/finance
rollout remains blocked.
