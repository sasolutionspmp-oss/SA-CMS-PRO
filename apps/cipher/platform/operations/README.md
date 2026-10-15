# Cipher development operations

The persistent synthetic runtime is documented in `../deployment/README.md`. These scripts operate on that development profile. They do not enable production accounting, external messages or a live model.

## HTTP acceptance

Run `python verify_r0.py --help` for available phases. Supply an ignored, private fixture JSON containing the synthetic users and project IDs. The verifier authenticates with real sessions, exercises the actual HTTP routes, and writes source hashes and redacted observations. Keep credentials, database backups and site configuration out of evidence artifacts.

`journey` verifies the connected project/document/task/Ricky boundary, scoped reads, CSRF, receipts, concurrency, byte hashes and pagination. Follow-up phases verify persistence after restart and explicit permission/lifecycle changes. Run these against a controlled synthetic fixture, coordinating permission changes with other test workers.

## Backup and isolated restore

`backup-synthetic.sh` runs the supported Frappe database/file backup after confirming synthetic mode. `restore-synthetic.sh` takes a backup prefix and restores into the isolated `cipher-restore.localhost` site, refusing an existing target. For another rehearsal set `CIPHER_RESTORE_SITE=cipher-restore-YYYYMMDDHHMMSS.localhost`; only that restricted target pattern is accepted. It pauses its scheduler and enables execution quarantine. It carries the encryption key from that backup's configuration snapshot into the restored site without exposing it or copying the source site's database credentials. It does not substitute the currently running site's potentially newer key.

Run the scripts in the Frappe bench container; the operations directory is not mounted there by default, so pass the script on standard input. Backups remain private in the sites volume. Do not remove an existing restored site simply to rerun a demonstration.

`verify_restore.py` runs with bench Python from the bench `sites` directory. It verifies restored project/Task data and exact artifact bytes, then confirms new effects and dispatch are quarantined. Evidence lives under `../../docs/framework/evidence/r0/restore-verification.json`. This development rehearsal does not establish a production recovery-time target or external-provider reconciliation.

Production deployment isolation, monitored capacity, secrets recovery, release upgrades and measured operational recovery targets remain the later operations work packages in the approved backlog.
