# Cipher development operations

The persistent synthetic runtime is documented in `../deployment/README.md`. These scripts operate on that development profile. They do not enable production accounting, external messages or a live model.

## HTTP acceptance

Run `python verify_r0.py --help` for available phases. Supply an ignored, private fixture JSON containing the synthetic users and project IDs. The verifier authenticates with real sessions, exercises the actual HTTP routes, and writes source hashes and redacted observations. Keep credentials, database backups and site configuration out of evidence artifacts.

`journey` verifies the connected project/document/task/Ricky boundary, scoped reads, CSRF, receipts, concurrency, byte hashes and pagination. Follow-up phases verify persistence after restart and explicit permission/lifecycle changes. Run these against a controlled synthetic fixture, coordinating permission changes with other test workers.

## Fresh-site checkpoint gate

Once the implementation sources are stable, run from the repository root:

```bash
python apps/cipher/platform/operations/validate_new_stack.py \
  --extended-fixtures \
  --output apps/cipher/docs/framework/evidence/r1/next-checkpoint-validation.json
```

Use a new report filename for each checkpoint or failed attempt. The runner
creates and retains a unique isolated `cipher-ci-*.localhost` site, leaving the
default development site unchanged. A separate `validation-reporter-tests` stage
first verifies the pure synthetic failure-report parser. It then checks the distribution supervisor
using actual disposable Linux processes, including separate-group work-horse
cleanup and preservation of an unrelated process. These checks are reported
separately from application/database tests. It installs and migrates the current app,
checks the locked runtime versions, verifies actual test collection, runs native
and ordinary tests and canonical extended procedures, then checks generated
clients, typecheck, production build and browser contracts from a clean frontend
installation. Supply the installed browser through `CIPHER_CHROME` when needed;
`--install-browser` is available for an environment that permits that download.

Canonical `run_acceptance` procedures must need no external fixture arguments.
Procedures requiring an existing private site fixture use a distinct entry point
and are listed separately as unexecuted by this gate. Their connected evidence
is captured independently. Missing, skipped, flaky or failed tests and source
changes during the run fail the checkpoint. Raw logs stay in the private work
directory identified by the report; do not publish those logs without review.

When the browser command fails, the runner reads its existing private Playwright
JSON report and attaches a bounded `browser_failure` summary to that failed stage.
It prints up to five cases to the job log and retains up to twenty in the public
validation JSON: test file/title/location, status, normalized assertion kind and
simple expected/received states, plus selected counts and duration. Raw assertion
values, raw expected/received numeric values, snippets, stacks, URLs, absolute paths, attachments and
stdout/stderr stay private. Missing, malformed or oversized reports are identified
without replacing the original stage failure. This diagnostic does not retry,
skip, alter browser assertions, or turn a failed process into a passing gate.
Report-level launch/setup errors use the same safe assertion categories, and
truncated traversal or error inventories are explicitly labeled. Timeout duration
and selected aggregate statistics remain public.

After reviewing the checkpoint and connected evidence, update the hash inventory:

```bash
python apps/cipher/platform/operations/record-evidence.py
```

The inventory reports current sources, artifact hashes and sources changed since
earlier captures. It does not turn old evidence into acceptance of new code.

## Backup and isolated restore

`backup-synthetic.sh` runs the supported Frappe database/file backup after confirming synthetic mode. `restore-synthetic.sh` takes a backup prefix and restores into the isolated `cipher-restore.localhost` site, refusing an existing target. For another rehearsal set `CIPHER_RESTORE_SITE=cipher-restore-YYYYMMDDHHMMSS.localhost`; only that restricted target pattern is accepted. It pauses its scheduler and enables execution quarantine. It carries the encryption key from that backup's configuration snapshot into the restored site without exposing it or copying the source site's database credentials. It does not substitute the currently running site's potentially newer key.

Run the scripts in the Frappe bench container; the operations directory is not mounted there by default, so pass the script on standard input. Backups remain private in the sites volume. Do not remove an existing restored site simply to rerun a demonstration.

`verify_restore.py` runs with bench Python from the bench `sites` directory. It verifies restored project/Task data and exact artifact bytes, then confirms new effects and dispatch are quarantined. Evidence lives under `../../docs/framework/evidence/r0/restore-verification.json`. This development rehearsal does not establish a production recovery-time target or external-provider reconciliation.

Production deployment isolation, monitored capacity, secrets recovery, release upgrades and measured operational recovery targets remain the later operations work packages in the approved backlog.
