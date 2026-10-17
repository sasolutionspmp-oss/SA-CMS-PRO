# Current actual Company evidence screens

These fifteen screenshots came from the reviewed production SAP UI5/Horizon build connected to the real isolated ERPNext/Frappe backend. Data is explicitly synthetic. Every POST was blocked; no API response or image was generated or mocked, no new login occurred and no model was invoked.

| View | Desktop | Tablet | Phone |
| --- | --- | --- | --- |
| Company-wide saved attachments | [1440](01-company-wide-attachment-register-1440.png) | [900](01-company-wide-attachment-register-900.png) | [390](01-company-wide-attachment-register-390.png) |
| Reopened original attachment | [1440](02-reopened-original-attachment-1440.png) | [900](02-reopened-original-attachment-900.png) | [390](02-reopened-original-attachment-390.png) |
| Stored predecessor comparison | [1440](03-reopened-predecessor-comparison-1440.png) | [900](03-reopened-predecessor-comparison-900.png) | [390](03-reopened-predecessor-comparison-390.png) |
| Corrected manual form, unsaved | [1440](04-corrected-unsaved-manual-form-1440.png) | [900](04-corrected-unsaved-manual-form-900.png) | [390](04-corrected-unsaved-manual-form-390.png) |
| Human review, not submitted | [1440](05-reviewed-unsaved-form-not-submitted-1440.png) | [900](05-reviewed-unsaved-form-not-submitted-900.png) | [390](05-reviewed-unsaved-form-not-submitted-390.png) |

The stored attachment still points to the original 2.500000 quantity and unchanged estimate snapshot. Its actual saved successor 3.750000 is reviewed separately. The final two rows stage a proposed next quantity 4.250000 solely to inspect the corrected form; it was not saved. The confirmation checkbox uses a normal keyboard Space action and awaited checked state. Current eligibility is separate from historical recorded facts.

[Verification](verification.json) includes actual requests, reload/read results, zero commands, blocked-POST policy, exact source PDF hash, static/font/resource outcomes and screenshot hashes. [Build provenance](served-build-provenance.json) binds frozen/served files before/after. [Native preservation](../native-readonly-verification.json) proves no new business effects. Actual inner card/form and outer page widths passed. The PDF viewer intentionally scrolls internally. Screens show each actual scrolled workspace viewport, not all long-page content at once. Earlier R19 images and the separately retained visual defect remain in their original gallery.
