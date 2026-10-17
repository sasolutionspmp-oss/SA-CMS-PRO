# DOC-04 shared composition

Owner: local integration coordinator. These are additions to compose, not files
to copy over the Task/trial/shared contracts. Base: DOC03 backend
`9d937ae1e0c10bb989e8c59f494e2998e41a8a43`, with its shared fragments composed first.

1. Add `Cipher Semantic Index` to modules.txt and migrate the new owned DocType.
   Add `document.semantic.manage` to both exact scope ability sets and the Duty
   choices. Do not grant it automatically; read and manage remain separate.
2. Apply **both** native permission hooks in shared-additions.json. System Manager
   DocType metadata permission must never expose checkpoint JSON through native
   list/read/export. Controllers already reject writes outside the private plan.
3. Wrap semantic_index.api.call's four closed operations in the established v1
   boundary, authentication, CSRF and error envelope. They are deliberately not
   whitelisted yet. Merge API schema definitions, register the route catalog and
   regenerate shared OpenAPI/TypeScript once with the local Task changes. The
   prepare operation UUID identifies the rebuild; cancellation/status reference
   that original job UUID. Do not treat cancellation as a second rebuild receipt.
4. Enable only a dedicated long worker. Prepare enqueues after transaction commit.
   Worker checkpoints require the private dedicated_worker context and zero
   preexisting database writes. Read/write checkpoints require verified MariaDB
   session READ-COMMITTED; unsupported isolation refuses semantic work. Never
   change isolation or commit another request's work to bypass the gate.
5. Provider configuration is server-only under `cipher_semantic_index`. Supply
   every field listed in semantic_index.configuration.FIELDS, an actually observed
   Ollama tag/digest/dimension/protocol, a separately provisioned unnamed float32
   Cosine Qdrant collection, endpoints and timeout/body limits. Optional API key
   belongs in protected site configuration. Defaults are unavailable. No automatic
   model pull, collection creation, Docker change or provider fallback is supplied.
6. Compose source-change notifications after commit with an explicitly authorized
   current semantic manager and exact scopes. Rights revocation, supersession and
   lifecycle changes are refused immediately by query even before deletion runs.
   Reconciliation is bounded and resumable; follow its cursor/status until complete.
   Automatic cross-scope event fanout and a periodic operator schedule remain local
   composition work; there is no hidden all-Company service identity or global scan.
7. Qualify native worker restart, checkpoints/CAS, native permissions and concurrent
   revocation first. Then run actual local Ollama embeddings and Qdrant index/query/
   delete/recovery using retained provider versions/configuration hashes. Verify
   `nomic-embed-text:latest` locally rather than assuming its digest or 768 dimensions.
8. Integrate semantic retrieval into Ricky only after those checks. Results carry
   a fresh canonical page citation, a separate exact Unicode chunk span/hash, and
   the source selection/adoption provenance. Vector payloads never supply text.

Source delivery is not native/HTTP/UI or connected-provider qualification. No Task,
product, deployment, Ricky adapter, award, procurement or finance source is changed.
