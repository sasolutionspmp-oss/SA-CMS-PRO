# Persistent Cipher development runtime

The selected runtime is ERPNext 16.51.0/Frappe 16.52.0 with the new `cipher_aec` app, MariaDB and Redis. Exact image references and observed language versions are in `../versions.lock.json`. This is a synthetic development environment with no accounting, bank, email or model connection configured.

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

The manager starts web, short/default worker, long worker, scheduler, websocket and nginx processes inside one development container to avoid duplicating a 3 GB filesystem for each process. It stops the group when a required process exits. Production service isolation is a later deployment profile, not claimed by this development arrangement.

The same-origin app is at `http://127.0.0.1:18880`; direct backend diagnostics are on 18881 and require `Host: cipher.localhost`. Both ports bind loopback. Database/Redis ports are internal. Normal UI calls explicit Frappe whitelisted Cipher methods, with server-controlled identity and CSRF; no browser administrator token is embedded.

## Repeatability and limits

Named volumes retain database, sites/files, logs and queue data across container restart. The editable application is bind-mounted from the clean new worktree. A recreated runtime reinstalls its pinned app package before starting services; a network-free production image is still a later packaging task. Readiness is not automatically a statement that every module is accepted.

Document scanning is unavailable in this local profile. Only the explicitly synthetic configuration permits unscanned text/PDF qualification, with `not_scanned` status preserved. It is not an antivirus claim or a live-data policy. Ricky remains unavailable until an actual supported local-model connection is configured.

Use the actual HTTP acceptance verifier under `../operations/verify_r0.py`, with a private fixture JSON and source-bound evidence. Do not publish fixture passwords, site configuration, database dumps or provider tokens with screenshots/evidence.
