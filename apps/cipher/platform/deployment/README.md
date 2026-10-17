# Persistent Cipher development runtime

The selected runtime is ERPNext 16.51.0/Frappe 16.52.0 with the new `cipher_aec` app, MariaDB and Redis. Exact image references and observed language versions are in `../versions.lock.json`. This is a synthetic development environment with no accounting, bank, email or model connection configured.

For a normal local Docker installation, use the separate [portable trial profile](PORTABLE_TRIAL.md).
It builds the backend and UI into an image and provides isolated trial/integration
start, status, stop, backup and quarantined restore commands. The development
profile below retains its original managed-cloud assumptions.

## Storage preparation

The managed Docker daemon uses `vfs`. Upstream layer extraction exhausted its filesystem. `prepare-dev-image.py` streams the pinned upstream merged filesystem through crane into a single local image and preserves its user, working directory, environment, entrypoint and command. It neither changes daemon settings nor prunes other work. The imported image ID differs from the upstream digest; both are recorded. This development-only representation does not claim a vendor-built derivative image.

Obtain crane 0.20.3 from its official GitHub release, verify the Linux x86_64 archive SHA256 in `versions.lock.json`, and invoke:

```bash
python prepare-dev-image.py --crane /path/to/crane --receipt /private/local/image-receipt.json
```

Preserve the environment proxy and CA trust. Do not disable TLS validation. Allow adequate free space for the flattened image, one development runtime writable copy, database and artifacts.

## Start and install

Create an ignored `.env` with independently generated `CIPHER_DB_ROOT_PASSWORD` and `CIPHER_ADMIN_PASSWORD`; keep permissions 0600. These are synthetic local credentials, never committed or printed. Then run from this directory:

```bash
./docker-local.sh compose --env-file .env -f compose.dev.yml up -d
./docker-local.sh exec cipher-r0-runtime-1 bash /opt/cipher/deployment/bootstrap-site.sh
./docker-local.sh exec cipher-r0-runtime-1 bash /opt/cipher/deployment/install-cipher.sh
```

The runtime initially waits for `sites/.cipher-r0-ready`. Create synthetic fixtures using `bench --site cipher.localhost execute cipher_aec.install.seed_synthetic`, supplying `CIPHER_FIXTURE_PASSWORD` through the process environment; the seed returns IDs but no passwords. Build `../../product` with its locked npm dependencies. Finally create the readiness marker:

```bash
./docker-local.sh exec cipher-r0-runtime-1 touch sites/.cipher-r0-ready
```

The manager starts web, short/default worker, long worker, the fixed distribution service pair, scheduler, websocket and nginx processes inside one development container to avoid duplicating a 3 GB filesystem for each process. It stops the group when a required process exits. Production service isolation is a later deployment profile, not claimed by this development arrangement. The distribution pair runs the `cipher_distribution` consumer and the Company-only recovery publisher. Task effects stay on `short`. Adding its next-boot startup command does not start or supervise it in an already-running manager. Initial controlled burst tests and the separately launched development pair/restart evidence must be recorded distinctly; no automatic delivery readiness follows from configuration alone.

The same-origin app is at `http://127.0.0.1:18880`; direct backend diagnostics are on 18881 and require `Host: cipher.localhost`. Both ports bind loopback. Database/Redis ports are internal. Normal UI calls explicit Frappe whitelisted Cipher methods, with server-controlled identity and CSRF; no browser administrator token is embedded.

## Repeatability and limits

Named volumes retain database, sites/files, logs and queue data across container restart. The editable application is bind-mounted from the clean new worktree. A recreated runtime reinstalls its pinned app package before starting services; a network-free production image is still a later packaging task. Readiness is not automatically a statement that every module is accepted.

The explicit installer, development manager before child startup, and fresh-site validation runner select the persistent native award profile using `cipher_aec.awards.runtime_install.configure_native_profile`. This non-whitelisted operator entry requires the synthetic site Administrator. It writes site-local `disable_global_search=true` before `cipher_award_native_profile="cipher.award.native.no-side-effects.v1"`, through Frappe's supported configuration writer, and verifies fresh typed readback. Repeated setup is idempotent; an unexpected existing profile refuses for operator reconciliation. It preserves unrelated site and common configuration, including scheduler and server-script settings. It is not called from automatic migration or a business transaction and does not enable an award action.

For an existing runtime, execute that same operator entry in a serialized configuration window, then separately reload the web/worker processes before qualifying native award guards. Persistent selection does not prove that loaded workers or native callbacks satisfy the profile. An interrupted setup may leave search suppression selected without its profile marker; repeat the same entry to finish. No automatic compensation turns indexing back on.

This profile suppresses normal native global-search indexing sitewide, including the Project and Sales Order paths used by award creation. Existing native global-search entries and queued payloads are not purged, and guest/authenticated native search reads and low-level direct calls are not disabled by this setting. Canonical permission-scoped Cipher search remains the application search. No existing native search data, callback configuration, notification, queue or business record is changed by profile setup. The runtime guards separately check current and effective callback/configuration/source state before native allocation.

Document scanning is unavailable in this local profile. Only the explicitly synthetic configuration permits unscanned text/PDF qualification, with `not_scanned` status preserved. It is not an antivirus claim or a live-data policy. Ricky remains unavailable until an actual supported local-model connection is configured.

Use the actual HTTP acceptance verifier under `../operations/verify_r0.py`, with a private fixture JSON and source-bound evidence. Do not publish fixture passwords, site configuration, database dumps or provider tokens with screenshots/evidence.

The development manager applies the supported `cipher_aec.integrations.distribution_install.configure_queue` operator helper before starting child processes. This preserves unrelated common worker entries and registers only `cipher_distribution` with timeout 120; native RQ otherwise rejects unknown queues. For an already-running site, apply the helper and gracefully reload web processes to discard cached queue catalogs before starting the pair with `python /opt/cipher/deployment/run-distribution-services.py` inside the runtime. The pair accepts no runtime-selected target, queue or site and does not install policies, grant duties or enable general cron. Only one pair may be active for this development profile.

Each pair child has its own process session. SIGTERM/SIGINT requests a warm shutdown, followed by a bounded 10-second wait and termination of remaining processes in those sessions, including RQ work horses that create separate process groups. This leaves time for cleanup within the parent manager's 15-second deadline. An unexpected child exit stops its sibling and exits unsuccessfully; the existing development manager/container owns restart. A pair launched separately into an already-running container has its own child supervision, but its outer restart remains operator-managed until the full manager next starts. Record that distinction in actual evidence. Configuration/source presence alone does not establish enqueue, consumer or restart readiness.
