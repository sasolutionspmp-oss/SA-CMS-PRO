# QA-01 fresh validation

The new-stack runner is `platform/operations/validate_new_stack.py`. It never
invokes the legacy Cipher engine or uses legacy acceptance counts. It requires
the pinned development bench, MariaDB, and Redis from `versions.lock.json`.

```sh
python apps/cipher/platform/operations/validate_new_stack.py --extended-fixtures --output apps/cipher/docs/framework/evidence/r0/fresh-validation.json
```

The runner creates a unique `cipher-ci-*.localhost` site and refuses an existing
target. It installs ERPNext and the editable custom app, migrates, explicitly
marks the site synthetic, pauses its scheduler, and seeds its synthetic masters.
It retains the site and private diagnostic directory for review. It does not
select a default site, drop a site, change the main fixture, or create another
runtime image/container. Positive-effect tests require an unquarantined CI site;
the paused scheduler prevents shared periodic dispatch of its fixture records.
Explicit worker tests use their own isolated queues.

The actual Frappe application suite produces JUnit XML. The runner checks that
test identities are unique, the suite is nonempty, and there are no failures,
errors, or skips. `--extended-fixtures` also invokes each reviewed
`test_*_acceptance.py:run_acceptance` entry against that site. Its AST must contain
that explicit bench entry, its command must succeed, and its structured result must pass. These
include real database/Redis/worker behavior with deliberately labeled synthetic
adapter responses. They never establish a real model/provider connection.
Separate host/HTTP procedures without a bench `run_acceptance` entry are listed
as unexecuted procedures in the report. They require their own HTTP environment
and evidence; they are neither counted as tests nor silently qualified.
The validation bootstrap installs the app's `validation` extra and the pinned
`unittest-xml-reporting==3.2.0` test reporter. Native integration tests use Frappe's
integration runner. Ordinary `unittest.TestCase` classes use one standard unittest
suite, because Frappe's explicit unit category omits ordinary TestCase classes.
Each case runs once and separate XML reports bind both collections. Missing
reporter text fallback and empty/concatenated XML cannot silently qualify a run.

The frontend is copied into a private temporary workspace. A fresh `npm ci`, API
type regeneration comparison, typecheck/build, and Playwright contract suite run
there, leaving the live development `node_modules` and `dist` untouched. The
browser contract tests use explicit HTTP fixtures; connected UI browser captures
remain separate evidence. Supply an installed Chromium with `CIPHER_CHROME`, or
use `--install-browser` in an ephemeral CI job.

Reports bind the source inventory before execution, detect changes during the
run, record actual runtime versions, per-stage duration, exit status and private
log hashes, and enforce stage/overall time limits. A changing source tree cannot
receive a passed fresh-validation report. Raw logs remain private and are not
automatically uploaded. The source inventory excludes generated caches,
`node_modules`, `dist`, and editable-install `.egg-info`; historical captures are
never rewritten when this exclusion changes.

The GitHub workflow `.github/workflows/cipher-new-stack.yml` prepares the locked
upstream ERPNext image on an ordinary Ubuntu Docker runner, uses the locked
MariaDB/Redis images, generates ephemeral synthetic credentials, and calls the
same runner. It uses immutable action revisions and uploads only the structured
validation JSON. Its runtime manager can remain behind the readiness marker:
these fresh database/fixture checks do not require a public HTTP service. The
standalone Vite browser contract server is local to the job.
The hosted workflow changes ownership only of the custom-app bind directory so
the image's UID 1000 can write editable package metadata from a hosted UID 1001
checkout. It does not change ownership of private environment files.

Local runner validation and an actual hosted workflow execution are separate
claims. The workflow subsequently passed in GitHub Actions for commit
`294d06d750c88e65b273b1ea727e8b84d593b3d9`:
[run 38763239781](https://github.com/sasolutionspmp-oss/SA-CMS-PRO/actions/runs/38763239781).
[Hosted provenance](hosted-validation-provenance.json) records the successful job
steps and artifact metadata, including the workspace artifact-download limit.
Later source changes require relevant new verification. This file and the
workflow are procedures, not substitutes for execution evidence.

## Recorded local execution

`fresh-validation.json` passed on the fresh isolated site
`cipher-ci-20261015154105-a1d7f2.localhost` in 171.758 seconds. All 116 unique
backend cases passed: 32 native integration cases and 84 ordinary unit cases,
with no errors, failures, skips, or missing declared cases. The estimating,
migration, outbox, and Ricky explicit acceptance procedures passed against this
site. Clean frontend installation, generated-client consistency, typecheck/build,
and all 17 browser contract cases passed with no unexpected, flaky, or skipped
cases. The source inventory did not change during execution. The site remains
available for inspection; no main-site fixture was changed by this runner.

Earlier attempts remain intact:

- `fresh-validation-initial.json` records the stale OpenAPI catalog artifact
  failure. The API owner regenerated that artifact before subsequent runs.
- `fresh-validation-reporter-initial.json` records the runner's invalid assumption
  that Frappe's unit category collects ordinary unittest cases. The corrected
  runner uses separate native integration and standard unittest collections.
- `fresh-validation-registry-initial.json` records 116 passing backend cases and
  the harness rejection of a host-only migration HTTP procedure. The corrected
  runner reports this separate procedure without invoking or qualifying it.

The final pass qualifies this local fresh gate. Hosted GitHub execution, the
separate migration HTTP procedure, and connected model/provider behavior require
their own evidence and are not inferred from this result.
