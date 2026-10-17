# Cipher: corrected actual Company workspace captures

These screenshots show the corrected SAP UI5/Horizon application served at `http://127.0.0.1:5196`, connected to the isolated ERPNext/Frappe backend on port 18886 using its original site Host. They show the existing `ricky-company-1cc066dc8ba8` synthetic fixture. Every API response came from that backend. The capture reused a private copy of the original author cookies, without login or logout.

| Page | Desktop | Tablet | Phone |
|---|---|---|---|
| Pursuit register | [1440 px](01-pursuits-1440.png) | [900 px](01-pursuits-900.png) | [390 px](01-pursuits-390.png) |
| Saved estimate and authored lines | [1440 px](02-estimate-1440.png) | [900 px](02-estimate-900.png) | [390 px](02-estimate-390.png) |
| Stored source document | [1440 px](03-document-1440.png) | [900 px](03-document-900.png) | [390 px](03-document-390.png) |
| Embedded Ricky read selection | [1440 px](04-ricky-selection-1440.png) | [900 px](04-ricky-selection-900.png) | [390 px](04-ricky-selection-390.png) |

The additional [390 px estimate action menu](02-estimate-actions-390.png) shows the accessible **Company estimate actions** overflow and **Calculate Company revision** action. Calculate was never clicked. At 390 px the estimate heading measures **238.844 × 62.375 px**, and its header is **111.375 px** tall. The original collapsed heading and 1379 px header remain preserved in the [original failed phone capture](original-phone-layout-failed.png) and private execution archive.

All 13 images were visually reviewed. The corrected estimate heading remains readable across all three widths. The document heading wraps into four readable lines at 900 px; narrow tables display the currently visible horizontal columns. The other pages and assistant selection retain their existing composition.

The successful capture made **19 API requests, all GETs**, with zero business writes, Ricky commands, login/logout requests, blocked requests, browser errors, console warnings/errors, or HTTP/resource errors. All **21 font responses were HTTP 200** and the browser font set finished loading. A GET-only browser guard prevented any write from being sent. No API response was mocked. A first capture attempt stopped on a raw DOM progress-indicator count after the actual page had loaded; its script, screenshot and diagnostics remain in the private `first-progress-indicator-check` execution archive. The successful capture checks accessible loading indicators.

Only `src/CompanyEstimates.tsx` and `tests/company.spec.ts` differ from the frozen R9 frontend. API generation checking and the build passed before capture. Source/build hashes use the exact sorted file manifest and algorithm recorded in [source-build-hashes.json](source-build-hashes.json):

- Source SHA256: `83f5a9b05236a4bfae9dc5e045ac8b49502ccdb4742541fe9f11aad9d95e39c4`
- Build SHA256: `a41ea113376cfb871b0ccbb1be9db222b72b8c973f0fc4fcf10e1a3c212936f6`

The first complete Playwright run finished **189 passed, 1 failed**, with zero skips. Its unrelated cost-rebase test failed at `locator.check` with “Clicking the checkbox did not change its state,” before the fixture released the delayed newer head. The unchanged test passed its single targeted retry in 3.931 seconds. The original report, screenshot and trace remain intact. The separately authorized complete confirmation then passed **190/190 cases**, with **zero skips, failures or retries**, in **376.420 seconds**. Every source/build byte still matches the captured manifest. Its independent report and hashes are recorded in [qualification-summary.json](qualification-summary.json).

These captures establish connected rendering and selection UI with synthetic business data. They do not establish model integration or backend workflow completion. Ricky was not run; no model was invoked. Native workflow and concurrency evidence belong to the separate backend qualification. Session material and raw private diagnostics are not publication artifacts. The capture task changed no main source or deployment. Root separately bound these source files into the published combined snapshot.
