# R0 HTTP acceptance evidence

The final actual journey capture, `http-journey-final.json`, passes eleven grouped
checks over 90 HTTP requests. It includes synchronized UUID/version recovery,
bounded signed cursors, UTC history, real source bytes/citations, native mapper
and legacy `cmd` denial, and honest unavailable-model behavior. This is one
journey capture; repeated authentication and earlier captures are not added into
a cumulative test count.

| Actual capture | Result |
|---|---|
| `http-restart-readback.json` | Original Task/receipt, exact original bytes/citation, and failed model run persist after runtime recreation |
| `http-source-revoked.json` | Project reads retained; document/run reads, original receipts/replay, and new upload denied for both account aliases |
| `http-task-read-only.json` | Task creation, native assignment, and mapper denied; Task assignment/version unchanged |
| `http-native-artifact.json` | Administrator-confirmed actual private URL denies owner/outsider; governed download retains exact SHA-256 |
| `http-closed-project.json` | Closed Project preserves original Task replay and refuses a fresh effect |
| `http-project-revoked.json` | Both aliases lose scoped data, private receipts, retries, and new effects after Project-read revocation |

The actual model request reached terminal `failed/upstream_unavailable` with no
answer. Connected-model inference and its cited-answer portion of C01 remain
blocked. `not_scanned` is retained for the synthetic source; no antivirus, OCR,
embedding, CAD, provider, or operational identity qualification is implied.

This folder records qualification of the new Frappe/ERPNext application. Legacy
prototype tests and model fixtures do not qualify this application.

The HTTP verifier uses ordinary authenticated Frappe sessions against an explicitly
synthetic site. Credentials stay in a local fixture manifest and are excluded from
the evidence. It must refuse mutation until the site identifies itself as synthetic.
The verifier creates only clearly labeled synthetic Tasks and documents; it never
targets an operational site or uses company records.

Required checks:

- An authorized user reads its Project and an independent user cannot read the
  Project, Tasks/history, document metadata, excerpts, citations, original bytes,
  or original operation receipts.
- Two authenticated accounts bound to one canonical person share a UUID namespace.
  Identical Task retries return the original Task and durable receipt. Reusing that
  UUID with changed fields or another command returns a conflict without an effect.
- Missing and stale source preconditions fail before Task creation. A reviewed
  proposal becomes stale when its source revision changes.
- Revoking the current duty prevents new effects and access to private original
  receipts, even when the request repeats a previously successful operation.
- Uploaded original bytes and citation checksums agree with the known synthetic
  source. A restart retains records, bytes, and receipt readback.
- Ricky connection status reports actual capability. An unavailable model is a
  blocked inference dependency, not a passed connected-model journey.

Each generated evidence JSON includes UTC execution time, Git/source fingerprints,
actual runtime versions supplied through the operator's fixture manifest, synthetic fixture identity, HTTP
status/envelope observations, and explicit limits. Browser, restart, worker-crash,
lease/fencing, and connected-model checks require their own actual evidence; the
HTTP verifier must not infer those outcomes from ordinary successful requests.

First actual HTTP run: `http-journey-first.json`, October 15, 2026, completed all
nine grouped HTTP checks against ERPNext 16.51.0 / Frappe 16.52.0 / Python 3.14.8.
It used 53 actual HTTP requests and created one synthetic Task and one real
two-page UTF-8 document. This first run began before the orchestration hold for a
parallel integration-test fixture arrived. A separately coordinated final run is
required after that exclusive test slot finishes; the first run is retained as
the actual preliminary capture. Ricky reported unavailable, so this run does not
qualify the cited-answer/model portion of C01. Restart/revocation/browser gates
remain separate until their actual procedures complete.

`http-journey-concurrency-initial.json` retains the next actual run, which passed
nine groups and failed the initial concurrency expectation: MariaDB correctly
returned a retryable `503 concurrent_change`, while the first harness expected an
immediate success/stale response. The harness was corrected to honor bounded
`Retry-After` and retry the original UUID and payload. The actual follow-up
`http-concurrency-recovery.json` passed and records two real 503 responses, each
with `Retry-After: 1`, followed by one effect/replay for a shared operation and one
success/412 refusal for competing operations. These captures are not added into
a larger unique test count. A later final journey qualifies the final source.

`http-journey-before-cmd-fix.json` retains the earlier green journey before the
legacy `cmd` regression was added. `http-journey-spa-target-initial.json` retains
the harness attempt that incorrectly expected a Frappe denial from nginx's SPA
root. The corrected final capture uses the explicitly supplied direct backend
origin for that root query and the normal same-origin proxy for the conflicting
API-path query. Both actual Frappe dispatcher variants are denied. Historical
captures retain their original source fingerprints and results.

Run from the repository root with a credential-bearing fixture manifest kept
outside tracked evidence:

```sh
python apps/cipher/platform/operations/verify_r0.py --fixture /tmp/cipher-r0-fixture.json --output apps/cipher/docs/framework/evidence/r0/http-journey.json
```

The manifest has `fixture_id`, `base_url`, `company`, `project`, and
`users.{primary,alias,outsider}.{user,password}`. Primary and alias must resolve to
the same registered person; outsider must be an independent person with access
to a different project. The seed helper returns identities but never passwords;
the operator supplies the same generated secret privately to the helper and
local manifest.
The optional `runtime_versions` object records the actual bench/runtime version
capture. A development virtual host can use `host_header` with a loopback
`base_url`; ordinary same-origin proxy access needs no override.

After an independently recorded actual service restart, repeat with
`--phase readback --previous .../http-journey.json` and a new evidence output path.
This phase reads the original receipt and replays the original operation, so it
does not confuse creating another Task with persistence proof.

For revocation, use the synthetic Administrator's bench-only
`cipher_aec.install.set_synthetic_duty` helper to deactivate the primary person's
`project.read` duty for the fixture project, then run `--phase revoked --previous
.../http-journey.json` with a new output path. Both account aliases must lose
access to the original receipt, original retry, and new effect. Restore the
synthetic duty afterward. Record the actual bench calls and results separately;
the HTTP client never administers or guesses real authorization state.

Additional coordinated phases use the same `--previous` final journey capture:

- `source-revoked`: retain `project.read`, revoke `document.read` and `ricky.run`.
  Project/Task reads must work while original upload/run receipts, replay,
  snippets, citations, original bytes, new upload, and model run/events are denied.
- `closed`: close the synthetic Project. Original Task receipt/retry must remain
  readable and return the same Task; a new logical operation must fail as closed.
- `task-read-only`: retain `project.read`, revoke `task.create`. The product
  command, native assignment and ERPNext timesheet mapper must refuse the reader.
  The native Task assignment/version must remain unchanged. The catalog denies
  ordinary-user ToDo enumeration, so an independent Administrator/bench readback
  must supply the matching ToDo row-count comparison.
- `native-artifact`: supply `native_artifact.{revision_id,file_url}` in the private
  fixture from an actual Administrator/bench read of the saved revision's File.
  The actual private source URL must deny both original uploader and outsider.

Only the root operator changes and restores fixture duties/status between phases.
Those state changes require their own actual command/result evidence. The journey
also issues synchronized HTTP requests through primary and alias sessions to
check same-operation serialization and competing-version refusal. Native File
metadata and ZIP routes are probed for both original uploader and outsider. The
actual private-file URL uses the separate Administrator-supplied readback above.

The actual Ricky run created for receipt/revocation checks is allowed to be queued
or to fail because the existing model adapter is unavailable. Its real persistence
is evidence of orchestration storage; it is never substituted for a cited answer
or connected-model qualification.
