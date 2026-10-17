# Actual Company drawing takeoff screens

These twelve screenshots were captured from the reviewed production SAP UI5/Horizon build connected to the real isolated ERPNext/Frappe backend. They use explicitly synthetic business data and the original authenticated session. No API response or screenshot was generated or mocked; no model or new login was invoked.

| View | Desktop | Tablet | Phone |
| --- | --- | --- | --- |
| Company takeoff register | [1440](01-company-takeoff-register-1440.png) | [900](01-company-takeoff-register-900.png) | [390](01-company-takeoff-register-390.png) |
| Authorized stored drawing | [1440](02-authorized-company-drawing-1440.png) | [900](02-authorized-company-drawing-900.png) | [390](02-authorized-company-drawing-390.png) |
| Reviewed manual quantity | [1440](03-reviewed-manual-quantity-1440.png) | [900](03-reviewed-manual-quantity-900.png) | [390](03-reviewed-manual-quantity-390.png) |
| Independently read saved measurement | [1440](04-saved-manual-measurement-1440.png) | [900](04-saved-manual-measurement-900.png) | [390](04-saved-manual-measurement-390.png) |

The latest capture is read-only: every POST was blocked, and the entry form was filled for review without submitting it. It reuses the original document/set and exact saved measurement from a separate successful native continuation after a [retained OCR dependency failure](../retained-original-native-failure.json). The earlier continuation's sole new write saved an explicitly manual quantity of 2.500000 in the original canonical length unit at precision six. No geometry or physical scale was inferred from drawing pixels. The displayed unit symbol is the actual synthetic canonical master value.

[Verification](verification.json) records actual GETs, zero commands, exact PDF download SHA, fonts, errors and overflow checks. The [native outcomes](../native-outcomes.json) retain the three earlier original command UUIDs and saved results. [Served build provenance](served-build-provenance.json) binds all frozen build hashes before/after and verifies actual static response bytes during capture. The [independent native audit](../continuation-epoch-verification.json) confirms the earlier one measurement/receipt/history addition. The [read-only follow-up audit](../responsive-read-only-preservation.json) confirms no new business changes and preservation of closed evidence. PDF content can scroll within its bounded viewer; no outer horizontal page overflow occurred.
