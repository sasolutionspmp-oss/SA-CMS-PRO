# Company cost setup: qualified UI variant 2

The actual isolated synthetic ERPNext/Frappe Company now has an authored cost code and cost type, each with an immutable successor revision. [Actual continuation evidence](actual-fourth-verification.json) records **one** remaining UI save and independent readback of all four original revisions. The first three successful commands were preserved from the earlier attempt and were never repeated; their incomplete captures remain in [the attempt history](../attempts/README.md).

The register deliberately shows the revision effective on **October 15, 2026**, alongside the latest saved revision, effective **October 16, 2026**. Dates, accounting targets and original IDs remain unchanged across UTC rollover.

| Screen | Desktop | Tablet | Phone |
|---|---|---|---|
| Cost codes | [1440px](actual-cost-code-register-desktop.png) | [900px](actual-cost-code-register-tablet.png) | [390px](actual-cost-code-register-phone.png) |
| Cost types | [1440px](actual-cost-type-register-desktop.png) | [900px](actual-cost-type-register-tablet.png) | [390px](actual-cost-type-register-phone.png) |

The corrected interface uses the pinned official settings icon, official SAP 72 font CSS and locally bundled licensed font bytes. UI5 target/status spacing and plain date/version wording are verified. The [settled read-only proof](settled-read-only-verification.json) requires title/context/action geometry and hit-tests before and after keyboard focus. It distinguishes the official sidebar animation from a persistent layout defect. Initial failures and the first mid-transition screenshot are preserved, not overwritten.

[Fixture contracts](fixture-browser-contracts.json) contain **19 unique cases**, each with one passed result and zero unexpected, flaky, skipped or retried results. These synthetic browser contracts are separate from actual cookie/CSRF/persistence evidence. The [118-source inventory](source-after.json), [907-file build inventory](build-inventory.json), [nine-client parity](generated-client-check.txt), [isolated build](isolated-build-log.txt) and [anonymous served-asset check](anonymous-readiness.json) bind this UI variant. No main runtime or main `product/dist` deployment occurred.

[Qualification and limits](qualification.json) scope this evidence to Company cost setup. It does not qualify award preparation, approval, Project creation, financial posting or operational identity. Actual raw request/response journals, auth material, exceptions, headers and browser traces remain private; only inspected screenshots and safe summaries are published here.
