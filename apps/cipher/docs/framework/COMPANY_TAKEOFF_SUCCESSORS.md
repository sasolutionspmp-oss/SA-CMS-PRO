# Revise a manual Company quantity

1. Open a saved manual measurement in **Company drawing takeoff** and choose **Author manual successor**.
2. Review the immutable original. Select an authorized current stored PDF revision/page for the replacement. A latest-family original can be revised when its earlier drawing source is no longer current; the new source must qualify independently.
3. Explicitly choose a canonical unit and author the new quantity, locator and reason. Acknowledge the original/replacement review. Inputs are not silently copied or rebased.
4. Save once. The canonical backend rechecks the exact latest-family predecessor and selected source inside its command transaction. A concurrent successor or stale source is refused; the client does not promise an atomic current-head preflight.
5. Inspect the independently read original/successor comparison. The stable family, predecessor, revision number, digests, sources and quantities must agree. The original remains immutable; existing estimate evidence keeps its original measurement and pricing.

An uncertain reply retains the original UUID, predecessor and authored inputs while this view remains mounted. Known access/identity changes hide source details; a sent uncertain command remains recoverable only under the original identity. Confirmed saves and later readback denial stay distinct. This is not a durable cross-reload command journal.

[Qualification](evidence/r1/company-takeoff-successor-r19/README.md) separates changed-drawing host fixtures from the actual same-drawing native quantity revision. [Twelve actual screens](evidence/r1/company-takeoff-successor-r19/ui/README.md) show the complete flow. Calibration, acceptance, automatic binding moves, repricing and model/accounting effects are outside this working increment.

[Reopen saved evidence and predecessor comparisons](COMPANY_TAKEOFF_HISTORY.md) after navigation or reload.
