# Actual Company quantity evidence screens

These twelve screenshots came from the frozen production SAP UI5/Horizon build connected to the real isolated ERPNext/Frappe backend. Records are explicitly synthetic. No screenshot or API response was generated or mocked; no model or new login was invoked.

| View | Desktop | Tablet | Phone |
| --- | --- | --- | --- |
| Existing saved manual measurement | [1440](01-existing-manual-measurement-1440.png) | [900](01-existing-manual-measurement-900.png) | [390](01-existing-manual-measurement-390.png) |
| Review the exact saved line | [1440](02-exact-saved-line-review-1440.png) | [900](02-exact-saved-line-review-900.png) | [390](02-exact-saved-line-review-390.png) |
| Independently verified saved attachment | [1440](03-verified-evidence-attachment-1440.png) | [900](03-verified-evidence-attachment-900.png) | [390](03-verified-evidence-attachment-390.png) |
| Original saved estimate after attachment | [1440](04-original-saved-estimate-1440.png) | [900](04-original-saved-estimate-900.png) | [390](04-original-saved-estimate-390.png) |

The flow reads the existing manual quantity, selects the dedicated saved synthetic line at the exact same quantity/unit/precision, records an explicit reason and human review, then saves one attachment. The unchanged saved estimate still shows quantity 2.500000 and USD3.13. Its canonical synthetic unit symbol is the stored master value, not an inferred drawing unit. Manual quantity evidence does not assert calibrated geometry.

[Verification](verification.json) records the actual requests, sole original browser UUID, fonts, errors and screenshot hashes. [Build provenance](served-build-provenance.json) verifies all compiled bytes before/after and sampled actual responses. [Independent native reconciliation](../binding-independent-verification.json) verifies the binding and exact preservation of all original records. The original [setup](../retained-idempotency-rejection.json) and [capture-helper](../retained-checkbox-driver-failure.json) failures remain separate. These captures preserve the actual scrolled internal workspace viewport; they do not claim to show all long-page content at once. No outer horizontal overflow occurred.
