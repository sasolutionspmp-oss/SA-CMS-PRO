# Actual saved-calibration screens

These six direct screenshots show the corrected SAP UI5/Horizon production build reading the real isolated ERPNext record. Data is synthetic. No image or API response was generated or mocked, no new login occurred and every POST was blocked.

| View | Desktop | Tablet | Phone |
| --- | --- | --- | --- |
| Reopened working calibration | [1440](01-reopened-saved-working-calibration-1440.png) | [900](01-reopened-saved-working-calibration-900.png) | [390](01-reopened-saved-working-calibration-390.png) |
| Original exact calibration references | [1440](02-original-unverified-calibration-references-1440.png) | [900](02-original-unverified-calibration-references-900.png) | [390](02-original-unverified-calibration-references-390.png) |

The record is unverified, geometric use is unavailable and no independent verification fact is reported. Two actual record GETs and reload/reselection returned the exact original saved calibration and digest. [Independent read audit](../corrected-readonly-verification.json) proves zero business effects. [Build provenance](served-build-provenance.json) binds actual served bytes to the 734-source/915-build freeze.

[The full capture report](verification.json) remains failed because an optional repeated pointer-helper assertion later raced UI rendering after the six completed images. That optional stage was not rerun. These images qualify the bounded saved-record read, not a wholly passed create flow on the corrected build. [Original real PDF anchor and reviewed-form images](original/README.md) came from the unchanged form before the validator correction. The original successful save was never repeated. Each image is the actual scrolled workspace viewport.
