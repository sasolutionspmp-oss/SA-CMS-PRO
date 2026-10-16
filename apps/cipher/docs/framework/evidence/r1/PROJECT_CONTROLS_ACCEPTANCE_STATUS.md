# Project controls qualification

The frozen controls foundation passed 22 focused pure/schema checks and one real
ERPNext native acceptance run with 10 meaningful groups (15.469 seconds) on the
isolated retained CI site. All 482 platform files in that execution snapshot
remained unchanged. The main runtime was untouched.

The native proof covers canonical master storage, same-Person alias retry and
payload conflict, exact case-sensitive native resource identity, current and
original source rights, effective revisions, disabled-original history, SQL
paging/count visibility, physical first-lock ordering, native 1020 fail-closed
RR promotion and fresh source resolution, and closed generic writes/factory
refusal. Restoration was independently checked on a new DB connection: native
read rights restored, no owned User Permission rows, exact own Account scope and
USD restored, no posting/Task/ToDo/award/WBS/budget effect, no pending mutation.

Post-fixture preservation has an explicit native tree delta. Of 56 tracked old
tables, 55 retain their full original row/column hashes. Creating the fixture's
Company through ERPNext's supported chart controller added 97 Accounts and
recomputed `lft`/`rgt` on all 291 old Accounts. Every other Account column remains
unchanged. The retained backup reconstructs the exact original full hash; the
27-column non-tree hashes match, and independent artifact review found all 564
original ancestor relationships unchanged. Full Account-row preservation did
**not** pass. No tree repair, rebaseline or fixture rerun occurred.

The proof uses frozen helper `1ac7dffb4661…`. A separately preserved optional
alternate-Currency fixture prerequisite correction was not copied or executed;
actual preflight already found nine eligible existing currencies. Earlier helper
and readback diagnostics remain preserved in the private operator directory.

Positive composed award/WBS/budget adoption, current public HTTP, posting,
certification floors and external providers remain unqualified. The award writer
and its activation remain inactive.

- [Native qualification and exact source/artifact hashes](project-controls-native-qualification.json)
- [Independent restoration and tracked-table readback](project-controls-independent-readback.json)
- [Exact original Account row/column deltas](project-controls-account-attribution.json)
- [Earlier pure/source evidence; final native hashes are in the qualification report](project-controls-source-clear.json)
- [Separate pending fixture correction](project-controls-alternate-currency-fixture-preflight.json)
