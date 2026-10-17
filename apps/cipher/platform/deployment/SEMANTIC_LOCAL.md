# Optional local semantic-index sidecar

Prepared for the DOC-04 source candidate `b70497f0`. These files do not start a
service, create a collection, select an embedding model, enable site configuration
or qualify semantic search. Existing trial, integration, backup and upgrade commands
retain their current behavior. Start this sidecar only in the separately authorized
synthetic provider-validation lane after the native permission gate.

## Exact image and client contract

The candidate's standard-library HTTP client uses **Qdrant 1.15.5 REST**, labeled
`qdrant-rest-v1`, over internal HTTP port 6333. Its collection verification requires
one unnamed vector of the separately verified dimension, `Cosine` distance,
`float32` or omitted datatype, and no multivector configuration. The client never
creates collections. Its server configuration remains disabled until the native
writer supplies a complete, verified opt-in profile.

Read-only Docker Hub registry inspection on October 17, 2026 resolved:

| Identity | Value |
|---|---|
| Official tag inspected | `qdrant/qdrant:v1.15.5` |
| Linux AMD64 manifest pinned | `sha256:53d8c371bc3ae99e4353897ee594bfcfab7f72c4925f74471ebb34d9f6103a3e` |
| Image configuration ID | `sha256:0ad2e23181e5646b286253c04cea23f07040ca313cc377d9fa7b21db184b6406` |
| Multi-platform index observed | `sha256:0fb8897412abc81d1c0430a899b9a81eb8328aa634e7242d1bc804c1fe8fe863` |
| Compressed image layers | 66,279,694 bytes |

The manifest and image ID are distinct. The Compose file pins the AMD64 manifest,
and the helper checks both identities. Registry metadata alone does not establish
the running server version; `status` separately reads its bounded root response
and requires exactly `1.15.5`.

The inline configuration uses the [official 1.15.5 configuration keys](https://github.com/qdrant/qdrant/blob/v1.15.5/config/config.yaml).
It explicitly disables gRPC with `grpc_port: null`, cluster mode, browser CORS and
telemetry. The [official entrypoint](https://github.com/qdrant/qdrant/blob/v1.15.5/tools/entrypoint.sh)
retains its termination handling, and [`--config-path`](https://github.com/qdrant/qdrant/blob/v1.15.5/src/main.rs)
selects the inline file. No curl, wget or Python is assumed inside the Qdrant image.

## Deliberate opt-in lifecycle

Use the selected local Docker Linux context and Compose 2.23.1 or later, which
supports [inline config content](https://docs.docker.com/reference/compose-file/configs/).
The existing integration profile must already own the bridge
`cipher-integration_default`. The helper refuses a trial bridge, missing image,
different architecture or unexpected existing sidecar. Nothing pulls implicitly.

From `apps/cipher/platform/deployment`, the native writer may later run:

```console
docker pull --platform linux/amd64 qdrant/qdrant@sha256:53d8c371bc3ae99e4353897ee594bfcfab7f72c4925f74471ebb34d9f6103a3e
python cipher-semantic.py check
python cipher-semantic.py start
python cipher-semantic.py status
python cipher-semantic.py stop
```

`check` only inspects the local image, existing bridge and any existing sidecar.
`start` explicitly selects Compose profile `semantic`; it never pulls an image or
changes a Cipher site. It reports a start request, not readiness. `status` admits
the actual container's image, ownership labels, unique bridge alias, storage and resource limits,
then reads the server version through the existing integration runtime. The probe
uses no proxy and performs only `GET /`; it does not infer collection, embedding,
write authorization, ACL or retrieval acceptance. Run status after startup finishes.

The dedicated Compose project is `cipher-semantic-integration`. Its only network is
the existing integration bridge, and its unique DNS alias is
`cipher-semantic-qdrant`. The later application endpoint is therefore
`http://cipher-semantic-qdrant:6333`; do not substitute a browser/host URL. No ports
are published. Bridge peers and local Docker administrators can reach the service;
this synthetic profile provides no API-key/TLS qualification. If the actual client
environment uses proxies, its effective `NO_PROXY` must cover the internal alias
before provider configuration is enabled. The status probe's proxy bypass does not
qualify the application's effective proxy configuration.

## Bounds, data and persistence

The sidecar has a hard 1-CPU quota, 512 MiB memory including swap, 128-process limit,
bounded Docker logs and no automatic restart. Search/API/indexing concurrency is
set to one, WAL segments are 8 MiB and only one collection is admitted. These are
trial limits for fewer than 1,000 synthetic points, not measured throughput targets
or a disk quota. Preserve at least 1 GiB of available local disk for the small
image, extraction overhead, WAL and rehearsal index, and measure actual usage.

The distinct volume `cipher-semantic-integration-qdrant-v1155` persists index data
and snapshots beneath `/qdrant/storage`. No sites, logs, database or original source
documents are mounted. The DOC-04 adapter admits only its closed metadata fields
and vectors; original text/snippets stay in canonical Frappe document storage and
are reread after authorization. Starting Qdrant itself does not enforce those
application payload rules for arbitrary direct API callers.

The base `cipher-local.py stop` **does not stop this sidecar**. Stop it separately
with `cipher-semantic.py stop`; its volume remains. Its restart policy is `no`, so
a Docker daemon restart requires another explicit start. To remove only its stopped
container/configuration while retaining its volume, use:

```console
docker compose --project-name cipher-semantic-integration -f compose.semantic.yml --profile semantic down
```

Remove the sidecar container before attempting to remove the base integration
bridge. Do not use volume deletion as a recovery step.

## Recovery and subsequent qualification

The base profile's backup/restore does not include this Qdrant volume, and its
restore configuration allowlist does not enable semantic providers. Frappe remains
the source of record for artifacts, ACLs and corpus generation checkpoints. The
index is derived data: later recovery must explicitly reconcile or rebuild it
from currently authorized canonical sources using the verified model/profile.
An index snapshot alone cannot establish those source or permission facts.

This package deliberately provides no collection creation, snapshot restore,
provider/profile enablement or cleanup command. The native writer must separately
verify one synthetic collection, actual model identity/dimensions, clean worker
transactions, write/readback, revoked-source refusal, deletion and restart recovery.
Keep default site configuration disabled until that work is admitted. A passing
server-version check does not qualify DOC-04 or a connected live-model capability.

Host-only refusal checks:

```console
python -m unittest discover -s tests -p test_semantic_sidecar.py -v
```
