# Company Activity R16 evidence

The selected Company's saved activity is available in the existing SAP UI5 shell. It uses the unchanged canonical history GET, signed cursors, current source permissions and generated `HistoryList` DTO. [Actual connected screens](ui/README.md) show the running implementation.

[Source manifest](source-manifest.json) freezes 704 source files and nine changed paths: four production UI files and five test files. All 550 platform/backend files and all 13 generated contracts remain byte-identical to R15; no schema, migration, provider or backend installation occurred. R15's 942 fresh backend checks remain source-applicable.

[Browser qualification](browser-qualification.json) covers 262 distinct composed cases: 239 unchanged earlier cases plus all 23 latest Activity/validation cases. The original full v1 run retained 256 passes and one failure because the static-asset check looked in the default build folder. The exact unchanged failed case passed separately against the existing qualified build. One preceding invocation selected zero cases and remains retained. V2's focused run passed 33 cases, including ten existing draft-save/navigation checks; typecheck, all 13 generated checks and the 911-file build passed. This is not a fresh full 262/262 run.

Root review found that a known domain permission change could leave old Activity rows mounted. Four regressions failed first on the original production source. The only production change between v1 and v2 adds full sorted capabilities to the Company/User/Person remount identity. All four now pass; reordering identical capabilities preserves the page. Original source, failed reports, contexts and traces remain retained separately.

The actual read-only capture used three API GETs and nine screenshots, no business command or model. It preserved inventoried business rows and all closed R15 evidence. Main remains on its existing release. Exact totals, exhaustive history latency, live model/provider integration, manual screen-reader review and enterprise qualification remain separate.

[Publication checks](publication-checks.json) verify the exact source, unchanged required legacy sources, known private-credential scan and local documentation links.
