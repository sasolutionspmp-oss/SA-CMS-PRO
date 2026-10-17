# Actual manual successor screens

These twelve archived native screenshots were captured from the frozen production SAP UI5/Horizon build connected to the real isolated ERPNext/Frappe backend, using explicitly synthetic records. No screenshot or API response was generated or mocked.

A later [visual review](../visual-review.json) found inner phone clipping in the original successor form. R20 contains the corrected layout and latest read-only captures; this gallery preserves the exact original source and native business epoch. The outer overflow check passed but did not qualify inner containment.

| View | Desktop | Tablet | Phone |
| --- | --- | --- | --- |
| Original manual quantity | [1440](01-original-manual-measurement-1440.png) | [900](01-original-manual-measurement-900.png) | [390](01-original-manual-measurement-390.png) |
| Explicit successor review | [1440](02-reviewed-manual-successor-1440.png) | [900](02-reviewed-manual-successor-900.png) | [390](02-reviewed-manual-successor-390.png) |
| Independently verified comparison | [1440](03-verified-successor-comparison-1440.png) | [900](03-verified-successor-comparison-900.png) | [390](03-verified-successor-comparison-390.png) |
| Preserved superseded original | [1440](04-preserved-original-measurement-1440.png) | [900](04-preserved-original-measurement-900.png) | [390](04-preserved-original-measurement-390.png) |

The user explicitly changes the authored quantity from 2.500000 to 3.750000 on the same stored drawing page and canonical unit. The comparison reads both immutable versions, labels changed inputs and preserves the original estimate attachment. The final view reopens the original and truthfully reports it unavailable for new use because a successor exists. No calibrated geometry or new drawing revision is inferred.

[Verification](verification.json) records the one original command UUID, actual comparison/record reads, exact PDF download, browser/resource outcomes, hashes and outer overflow checks. [Build provenance](served-build-provenance.json) binds frozen/served bytes. [Independent native verification](../native-independent-verification.json) confirms the three declared additions and preservation of the original measurement, R18 binding and pricing snapshot. Screens show the actual scrolled internal viewport, not all long-page content at once.
