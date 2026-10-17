# Existing local Ricky / Ollama handoff

The reviewed `ollama-local-v1` adapter is implemented. The default remains
unavailable until an operator supplies its explicit site configuration. Host-only
model checks passed October 17, 2026; the persisted native-app answer and Task
journey remains a separate gate.

## Recovered contract and live observations

The existing independent source `C:\Users\TravisStaib\Ricky\src\ollama.ts`
uses native Ollama: `GET /api/tags`, `POST /api/chat` with `stream:false`,
`think:false` and bounded options, followed by another exact-name/digest check.
`POST /api/show` supplies health and provider-reported capabilities. Neither the
independent runtime's code nor its broader tools is imported into Cipher. The
implementation follows the official [Ollama API contract](https://github.com/ollama/ollama/blob/main/docs/api.md).

- Ollama `0.40.4` listens on Windows `127.0.0.1:11434`. Root separately verified
  `GET http://host.docker.internal:11434/api/tags` from the actual trial container
  without changing binds, firewall or security settings. No relay is needed.
- Existing selection `ricky-v9:latest`, digest
  `31f36cc2a1105c61c6d54d2ef5424400f7c2811adab5dc0d2ba30a18ec47bf2d`.
- Inventory size `16836928263` bytes. Provider reports `qwen35`, `27.3B`,
  `Q4_K_M`, and completion/tools/thinking. These observations do not establish
  training lineage, license provenance or full model qualification.
- A bounded native-tool probe returned exactly `cipher_probe({"value":"ready"})`,
  empty assistant content, `done:true`, `done_reason:"stop"`, in 58.052 seconds
  including load. No requested function was executed.
- The reviewed Python adapter's no-tool schema probe returned
  `The synthetic review meeting is Thursday.` with exact citation
  `synthetic-review-001` in 19.656 seconds. Name/digest checks ran before and after
  inference. The live evidence pins the tested source snapshot; subsequent
  validation-only hardening preserves the same short selected-model behavior.

Evidence: `apps/cipher/docs/framework/evidence/r3/ricky-local-ollama` from the
repository root. These are host model proofs, not Frappe/DB effects.

## Closed site-operator configuration

Only the site operator sets these keys. The browser/model/app user cannot choose
a URL, model, Python path or resource limit. The endpoint reference resolves a
closed server-side record. Selection must match that record. The recovered
unauthenticated local contract refuses a non-null secret reference; neither
record contains a secret value.

```json
{
  "cipher_ricky_connection": {
    "adapter_kind": "ollama-local-v1",
    "endpoint_reference": "ricky-local",
    "model_selection": "ricky-v9:latest",
    "connect_timeout_seconds": 10,
    "first_response_timeout_seconds": 120,
    "wall_timeout_seconds": 150
  },
  "cipher_ricky_ollama_endpoints": {
    "ricky-local": {
      "base_url": "http://host.docker.internal:11434",
      "model": "ricky-v9:latest",
      "digest": "31f36cc2a1105c61c6d54d2ef5424400f7c2811adab5dc0d2ba30a18ec47bf2d"
    }
  }
}
```

For a host process, use the explicitly observed `http://127.0.0.1:11434` instead.
Re-read inventory before installation. Digest changes require an operator update
after verification; the adapter never automatically adopts a changed alias.
Allowed HTTP hosts are exactly `127.0.0.1`, `::1`, `localhost` and
`host.docker.internal`, with an explicit port and no path, credentials, query or
fragment. There is no arbitrary remote URL or authenticated-provider mode.

## Limits and truthful capability status

Generation requests configure 8192 context tokens, 1024 output tokens,
temperature zero, four CPU threads and 60-second keep-alive. The provider's
reported 262144-token context and concurrency capacity remain unqualified.
The 150-second per-generation cap stays below the engine's 180-second lease and
also respects the run deadline and stricter profile timeouts. Socket watchdogs
bound dripped headers, chunk framing and bodies. Requests/responses are byte
bounded. Duplicate keys, nonfinite JSON, truncated/incomplete/wrong-model output
and unregistered/malformed tools fail closed. Persisted model version includes
the full exact model name and digest; model names are limited to 128 characters
to fit the engine's 200-character metadata limit.

The C01 native-app run exposed an unconstrained final-content failure with native
tools present. [C01 protocol correction](OLLAMA_C01_PROTOCOL.md) records the
preserved failure, bounded reproduction and candidate fix. Native selection uses
tools without `format`; genuine tool calls keep strict registered schemas. If no
call is returned, provisional content is discarded and a separate no-tools
JSON-schema final synthesis runs under the same total budget. A verified outer
Task-proposal receipt goes directly to constrained final synthesis. Response
sampling records protocol/prompt versions, actual phase names and model-request
count. A capability is confirmed only after validating that type of response in
the current instance; reports alone stay unverified. A fresh instance has no
durable capability attestation. Image input remains unavailable.

No provider cancellation API was recovered. `cancel` may close the current
instance's socket as a best effort, always returns false and never attests server
compute stopped. Cross-process cancellation relies on durable run cancellation,
fencing, bounded inference and checks before accepting outputs/effects. Saved
effects remain history.

## Verification and native handoff

```powershell
$env:PYTHONPATH='apps/cipher/platform/apps/cipher_aec'
python -m unittest cipher_aec.tests.test_ricky_ollama cipher_aec.tests.test_ricky -v
```

All 25 adapter tests, five intent tests and 27 existing orchestration tests passed. Real loopback
HTTP stubs cover proxy isolation, redirects, byte/framing limits, truncated
Content-Length, dripped headers/chunk headers/body, deadlines and cancellation.
Independent review checked normalization, identities, framing and metadata.
These contract tests use explicitly synthetic model responses.

Root owns installation, current project-duty/API integration and the serialized
native DB writer. Configure the candidate in the synthetic trial site, read
status from the actual app process, then supervise a persisted cited answer and
source-bound Task proposal/save/replay through the ordinary Task service. Recheck
permissions/sources and inspect durable model version/sampling metadata. This
lane made no Frappe configuration, installation, worker or Task changes.
