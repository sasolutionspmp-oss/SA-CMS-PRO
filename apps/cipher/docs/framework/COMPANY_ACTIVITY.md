# Company Activity

Open **Company activity** in the SAP UI5 navigation to read changes visible under your selected Company and current source permissions. A direct link can bind `/company/activity?company=<Company ID>`. It cannot fall back to another Company when that requested scope is unavailable.

Events appear newest first with the recorded actor, UTC timestamp and record type. **Record details** expands the original event code, exact timestamp, IDs and escaped details. **Open estimate**, **Open document**, **Open pursuit** and **Open proposal** are offered only for existing supported record routes; revision, Run, application and native references remain details. Actor names and owner relationships are never inferred.

The page uses the existing `cipher_aec.api.company.history` GET and generated `HistoryList`: `limit=25`, `count_mode=none`, `total=null`, opaque signed `next_cursor`. Next requests one page. Previous rereads under current authority. Refresh resets pagination. No exact count, eager page request, snapshot completeness or exhaustive-history performance is claimed.

Company, User, canonical Person and any known capability change immediately unmount the previous resource, abort pending reads and restart at page one. Capability order alone is immaterial. Denial, source failure, invalid cursor or malformed data hides the old rows. Current backend permissions still govern every requested page and destination. Existing unknown-save navigation protection also disables Activity record links, pagination and refresh.

[Qualification](evidence/r1/company-activity-r16/README.md) records the 704-file frozen source, 262 distinct composed browser cases, unchanged backend/contracts, 911-file build and retained failed attempts. [Nine real container screenshots](evidence/r1/company-activity-r16/ui/README.md) used three actual GETs without business writes. Independent comparison preserved all business rows in 78 inventoried tables, exact source/configuration/indexes and closed R15 evidence; only bounded original native User/Session heartbeat fields changed.

This read interface completes the bounded Company Activity item. Overall AI-04/UX-03, Company takeoff UI, live Ricky/QuickBooks connections, restored-site recovery and enterprise acceptance remain ongoing.
