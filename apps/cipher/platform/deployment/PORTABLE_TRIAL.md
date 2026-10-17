# Portable synthetic Cipher trial

This separate profile builds the current new `cipher_aec` backend and locked UI5
client into a derivative of the digest-pinned ERPNext/Frappe image. It needs no
flattened cloud image, editable source mount or host CA mount. The original
`compose.dev.yml` profile is retained.

Use Docker Desktop's Linux engine or Docker Engine with Compose v2, Python 3.12+
and Git. Keep at least 25 GiB free for the first build and its temporary layers,
database, uploads and backup rehearsal. Check actual free space before starting;
that allowance is a local trial estimate, not a measured production capacity.
Docker uses the selected normal context, including Docker Desktop. Use a native
Linux filesystem checkout inside WSL for better build performance when available.
Build requires network access; normal startup installs no packages.

From `apps/cipher/platform/deployment`:

```console
python cipher-local.py init
python cipher-local.py build
python cipher-local.py start
python cipher-local.py status
```

Open **http://cipher-trial.localhost:18890**. The first boot creates the real
MariaDB-backed ERPNext site, installs/migrates `cipher_aec`, selects its synthetic
native award profile and distribution queue, and runs the explicit
`cipher_aec.trial.seed_local_trial` initializer. Start waits up to 15 minutes for
the built UI and actual Frappe ping endpoint. Use `python cipher-local.py logs`
to inspect a failed boot. Read [the human trial guide](../../docs/framework/LOCAL_HUMAN_TRIAL.md)
for the actual role-based journeys and their current limits.

`init` creates three independent random credentials in
`.local/trial/environment`, which Git ignores. Open that private file locally to
obtain the Administrator and synthetic fixture passwords; the wrapper never prints
them. Keep the folder private to your OS account, especially on Windows where
POSIX mode bits do not replace Windows access controls. The fixture password is
shared only by this synthetic profile's registered test people. Passwords in the
environment are available to local Docker administrators.

Use separate browser hostnames for each profile. Session cookies ignore port
numbers, so using `127.0.0.1` for both profiles can replace the other session.
Both exposed ports bind `127.0.0.1`; database and Redis have no host ports. The
diagnostic backend is `http://127.0.0.1:18891` and requires `Host: cipher.localhost`.
Normal UI traffic uses the same-origin reverse proxy.

## Independent integration namespace

```console
python cipher-local.py --profile integration init
python cipher-local.py --profile integration start
python cipher-local.py --profile integration status
```

Both profiles initially use the same built image. Integration opens
**http://cipher-integration.localhost:18900**, with backend diagnostics on 18901.
The explicit Compose projects `cipher-trial` and `cipher-integration` each own
their own network, database, Redis, sites/files and logs volumes and generated
credentials. Each isolated bench calls its internal site `cipher.localhost`;
that shared internal spelling does not share a site or database. Integration is
still synthetic, with no provider, bank, mail or live-model connection.

## Stop, restart and source changes

```console
python cipher-local.py stop
python cipher-local.py start
```

Stop retains every volume. Startup checks the saved build identity; a normal
restart does not reseed people, reset passwords, reactivate duties or migrate
human trial records. Required services fail together, and Docker restarts the
runtime after an unexpected exit. The manager reuses the existing bounded Linux
process supervisor and its warm distribution-worker shutdown.

The image records the Git revision and a SHA-256 inventory of the application,
frontend and packaging inputs. A different build refuses an existing site's
marker. The integration-only command below provides an explicit offline upgrade;
ordinary startup never migrates a persistent site. Preserve the prior image and
private environment with its backup.
Build IDs identify source content; they do not claim bit-for-bit identical npm/pip
install artifacts or turn a local derivative into a vendor-built image.

## Explicit integration candidate upgrade

Finish the source/backend gate before building. Release every other writer using
the integration database, including separately launched native test lanes. Keep
the original `trial` profile on its qualified image. Run from this directory:

```console
python cipher-local.py --profile integration build-candidate
python cipher-local.py --profile integration upgrade --candidate .local/integration/candidates/EXACT_BUILD_SHA256.json --acknowledge-build EXACT_BUILD_SHA256 --writers-quiesced
python cipher-local.py --profile integration start
```

`build-candidate` assigns the unique tag `cipher-local:integration-EXACT_BUILD_SHA256`
and saves the immutable image ID, source build SHA-256, Git revision, offline
helper hash and Docker context/daemon in its private receipt. It does not change
either profile's selected image. A preexisting tag or receipt is never overwritten.
Retain build output and the receipt; if a build is interrupted after the tag exists
but before its receipt is written, inspect/reconcile its actual identity before
proceeding. Do not fabricate a receipt for an unverified image.

`upgrade` requires the exact candidate hash and the operator's assertion that
other writer lanes have been released. It holds an OS-owned integration lock,
checks the installed container and fixed integration volume namespace, retains
the old image under a unique recovery tag, and stops the complete runtime service
(web, workers and scheduler). It starts and waits for only the selected profile's
database and Redis if necessary; offline containers use `--no-deps`, explicit
entrypoints and no host ports. A surviving
one-off container blocks a new operation until it has finished and been reconciled.

The private `.local/integration/upgrades/EXACT_BUILD_SHA256/` directory preserves
the exact original environment, original marker/site/common configuration,
the old/candidate image identities, a fresh database/public/private/configuration
backup with all four hashes, and the stage journal `upgrade.json`. These files
include recovery secrets and must stay private. The native site also retains an
upgrade hold and backup intent/receipt. The shared default trial image tag is
never replaced by this command.

Only after that complete exported backup verifies does the candidate execute the
supported `bench --site cipher.localhost migrate`. The migration hook installs
the additive Task assignment fields without seeding users, resetting passwords or
provisioning duties. Fresh bench processes read installed applications and
`cipher_aec.projects.install.metadata_status`, including actual Task columns and
Custom Field definitions. The candidate marker is published only after this
readback passes; integration's environment then selects its immutable candidate
image ID. A final fresh readback releases the startup hold and records stage
`complete`. Services remain stopped until the explicit `start` above. This stage
receipt qualifies migration/install/readback only; perform native and browser
journeys separately before accepting features.

On failure or interruption, retain every journal, backup and image and use the
same candidate, exact hash and acknowledgement with `--resume`:

```console
python cipher-local.py --profile integration upgrade --candidate .local/integration/candidates/EXACT_BUILD_SHA256.json --acknowledge-build EXACT_BUILD_SHA256 --writers-quiesced --resume
```

The original environment, helper, Compose configuration, Docker context/daemon, container/volumes and
image identities must still match. Resume reuses the original backup and reruns
an interrupted migration idempotently when necessary. An interrupted backup is
reconciled against its original intent; if it lacks exactly one fresh complete
set, the command fails closed for offline reconciliation and never starts a
second backup against that intent. The wrapper blocks ordinary start/build/
backup/restore while a journal is pending. New images also refuse startup while
the native hold exists. The original older image has its original startup code;
keep its selected runtime stopped and do not bypass the wrapper with Docker
start/restart commands during an upgrade.

There is no database downgrade or automatic restart of old code. To rehearse
recovery using the retained host bundle and old image while integration remains
stopped:

```console
python cipher-local.py --profile integration upgrade-restore --candidate .local/integration/candidates/EXACT_BUILD_SHA256.json
```

This imports only the verified four backup files, refuses different existing
backup bytes, and reuses the supported restore/configuration helpers to create a
new `cipher-restore-YYYYMMDDHHMMSS.localhost` site. The restored scheduler remains
paused and execution quarantined. It preserves the active site's migration state
and hold, and records a separate restore receipt. Original backup passwords are
retained. Authenticated saved-record and exact-document-byte checks are separate
recovery qualification; switching/serving a recovered site is not implemented.

## Private backup and quarantined restore rehearsal

```console
python cipher-local.py backup
python cipher-local.py restore .local/trial/backups/EXACT_BACKUP_PREFIX
```

Backup reuses `operations/backup-synthetic.sh` to export Frappe's database, public
files, private files and matching configuration snapshot. The wrapper downloads
the complete set under `.local/trial/backups/` with a SHA-256 manifest and the
running image's source build identity. Restore refuses a different build. The
snapshot includes encryption recovery material; keep the entire bundle and
environment private and copy them to an approved recovery location. An optional
`backup --destination /private/path/new-bundle` selects a new host directory.

Restore checks all four hashes before contacting Docker, imports without replacing
different existing backup bytes, and reuses `operations/restore-synthetic.sh`.
It creates a new `cipher-restore-YYYYMMDDHHMMSS.localhost` site inside the selected
profile's bench. It refuses an existing target, carries the backup's encryption
key, pauses the restored scheduler and enables execution quarantine. It does
not overwrite or serve the active trial site. This is a rehearsal, not a
one-command replacement of the active site. No command deletes volumes or sites.

After the unchanged restore helper, the wrapper restores an explicit configuration
allowlist from that backup: synthetic mode, the document allowance only when the
source explicitly allowed it, and the recognized native profile/search suppression.
It retains scheduler pause and execution quarantine. Other source settings, database
credentials and provider configuration are not copied by this step. Restored users
retain the original backup passwords; the integration profile's newly generated
fixture password does not replace them. No users are reseeded or reset.

Keep quarantine in place and verify actual authenticated role reads and exact
document bytes before treating a rehearsal as usable recovery. Do not enable
delivery or resume a restored scheduler as part of this trial. Measured recovery
targets, operational secrets/identity, release upgrades and live integrations
remain separate qualifications.

## Packaging checks

Host-only boundary checks:

```console
python -m unittest discover -s tests -p "test_portable*.py" -v
```

Runtime acceptance must separately record an empty-volume boot, role login,
real create/read/reload journey, stop/start and container recreation, simultaneous
profile isolation, and complete backup/restore checks. A healthy ping does not
establish those application outcomes. The older `validate_new_stack.py` image
admission accepts its original upstream/flat development representation, so it
does not automatically qualify this derivative; retain package provenance and
actual runtime observations separately.
