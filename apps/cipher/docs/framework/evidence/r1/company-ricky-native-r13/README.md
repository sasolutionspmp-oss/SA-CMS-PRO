# Prospective Company Ricky command history

New Company Ricky Start and Stop commands now append one event to the existing canonical Company history chain, atomically with their command receipts. A replay appends nothing. Event metadata contains the action/status or status/cancellation flag; it contains no source text, selection, result, model text or session reference. The API response shapes remain unchanged.

The actual isolated Frappe/ERPNext sequence passed using the existing qualified identities and copied sessions in a separate journal:

1. A new authenticated Start returned its queued admission and created exactly one attributed history event linked to the previous Company chain head.
2. An ordinary RQ worker completed that Run with one deterministic invocation, zero model generations and no proposal. Worker execution created no command-history event.
3. With the author's exact source-read duty disabled, full result access and source-bearing Start replay were refused. A new source-free Stop succeeded on the already successful Run, appending a second event with `status=succeeded` and `cancel_requested=false`. The terminal Run, children and result bytes did not change.
4. Both new events stayed hidden during the source outage. Exact duty restoration returned the author to 11 visible events: nine existing events plus the two new facts. The same-Person alias saw its original nine, including neither new fact; the outsider remained denied. During the outage the author and alias each retained three independently readable events, so totals were filtered rather than forced to zero. The alias could not reuse the owner's paging cursor: actual HTTP 422 `invalid_cursor` matched the published schema.
5. Both original command UUIDs replayed without another event. The queued Start receipt stayed queued and both canonical receipt byte checks passed. Independent final readback preserved earlier business/orchestration/history/receipt rows, identities, duties, original fixture files/cookies and exact site configuration. No active Run, worker, queued job or started job remained.

All 782 unit tests passed in the installed Frappe environment. The unchanged 52 integration cases give 834 composed backend cases; eight existing native workflows, 190 browser cases and the exact 905-file UI build retain their preceding qualification. The change is one production API file plus three fixture/test files. No schema migration or UI rebuild was needed. The isolated web was reloaded once; main remains on its separately qualified release. The preceding [R12 hosted CI passed](https://github.com/sasolutionspmp-oss/SA-CMS-PRO/actions/runs/38859316748); this source checkpoint has its own subsequent CI result.

The host regressions force post-history and post-receipt failures through the actual API/command/history functions using a transactional SQLite adapter. They verify rollback of Run, event and receipt together; this is not native MariaDB failure-injection evidence. A failing copied-cookie provenance test and its correction are retained.

This adds prospective accepted command facts through the Company history API. It does not backfill older Runs or claim worker lifecycle history. A Company history interface, persisted reviewable suggestions and explicit human draft saves remain subsequent work. The live Ricky model and QuickBooks remain unconnected, and earlier crash/restore and large-history performance limits remain.

- [Native qualification, event attribution and phase hashes](qualification.json)
- [Source snapshot](source-snapshot.json)
- [Unit qualification](unit-qualification.json)
- [Focused source review and retained fixture failure](source-review.json)
- [Existing actual SAP desktop, tablet and phone screenshots](../company-ricky-native-r10/ui/README.md)
