# Actual Company Activity screens

These nine screenshots came from the qualified production SAP UI5 build on port 5204, using the real isolated ERPNext backend on port 18886 and the original authenticated author session. Business data is explicitly synthetic. No response was mocked, and no login, business command or model invocation was made.

| View | Desktop | Tablet | Phone |
| --- | --- | --- | --- |
| Newest saved changes | [1440](01-company-activity-first-page-1440.png) | [900](01-company-activity-first-page-900.png) | [390](01-company-activity-first-page-390.png) |
| Expanded original event details | [1440](02-company-activity-record-details-1440.png) | [900](02-company-activity-record-details-900.png) | [390](02-company-activity-record-details-390.png) |
| Requested next page | [1440](03-company-activity-next-page-1440.png) | [900](03-company-activity-next-page-900.png) | [390](03-company-activity-next-page-390.png) |

[Verification](verification.json) records three actual API GETs: session and the two requested history pages. Each page returned 25 visible events with `count_mode=none`, `total=null` and no eager next request. Fonts loaded; browser/resource errors, blocked requests and horizontal overflow were absent.

[Independent preservation](preservation.json) compared 78 inventoried tables and preserved all inventoried business rows, source, configuration, indexes and closed R15 evidence trees. One original User and one original Session heartbeat were independently validated within the browser time bounds; no timestamp was reset. Private before/after snapshots remain retained and are not published.

[Build provenance](served-build-provenance.json) binds the unchanged 911-file build before/after capture and 25 actual served-byte checks after capture. This proves the bounded screenshots and requested pages, not exhaustive-history performance or production/enterprise readiness.
