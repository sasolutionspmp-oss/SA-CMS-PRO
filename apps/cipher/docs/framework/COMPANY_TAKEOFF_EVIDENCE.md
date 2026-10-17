# Attach manual takeoff evidence to a Company estimate

1. In **Company drawing takeoff**, open a set and its saved manual measurement.
2. Choose **Attach to saved estimate line**, then an authorized Company estimate and one exact saved line. Estimates page in groups of 25; saved lines page in groups of ten, without an inferred exact total.
3. Review the saved revision, original quantity, canonical unit/precision and drawing reference. Enter a reason and check the explicit human review acknowledgment. Quantity, unit and precision must match exactly.
4. Submit once. The client rereads the current estimate head and current measurement eligibility before its first request. The canonical backend rechecks scope, authority and immutable dependencies.
5. Read the independently verified saved attachment. Its exact original line, measurement and pricing snapshot remain immutable. Later heads are labeled historical; no automatic retargeting or repricing occurs.

The existing API intentionally accepts exact historical saved lines and has no atomic current-head fence. The first-submit client preflight does not provide such a guarantee. An uncertain reply retains the original UUID, payload and reviewed revision while mounted; recovery never rebases the request. This is not a cross-reload journal. Known Company/User/Person/capability changes clear source-bearing state and abort an unsent preflight. Confirmed writes remain distinct from later readback denial or transient read failure.

The selector independently joins estimate/revision/snapshot/line and measurement/source/unit facts, validates published closed schemas and canonical digests, and checks result actor/operation identity. The backend remains authoritative. [Native qualification](evidence/r1/company-takeoff-binding-r18/README.md) and [twelve actual screens](evidence/r1/company-takeoff-binding-r18/ui/README.md) record this working increment and all retained driver failures. The attachment grants no acceptance, baseline, issue, award, financial or model authority. [Successor comparison](COMPANY_TAKEOFF_SUCCESSORS.md) is qualified in R19; calibration remains ongoing.

[Reopen saved evidence and predecessor comparisons](COMPANY_TAKEOFF_HISTORY.md) after navigation or reload.
