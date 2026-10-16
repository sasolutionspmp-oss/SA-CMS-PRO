# Preserved connected UI attempts

These are actual browser captures from the isolated ERPNext backend and the original SAP UI5/Horizon build. None is a completed cost-administration or award acceptance. [Provenance](provenance.json) binds the backend, UI and original command journal.

- `01-zero-command`: the first helper stopped before a business command.
- `02-three-cost-commands`: cost-code creation/revision and cost-type creation saved successfully and were independently read back. The helper then waited for a stale display label before the fourth command. Desktop/tablet/phone captures show the persisted cost-code register; the overall attempt contains unresolved errors.
- `03-read-only-diagnosis`: normal App sign-in returned 401 then 200 without the previously observed 503. The original account identity and three-command journal stayed unchanged. A helper role assertion failed despite the visible dropdown. Raw private diagnostics identified the missing SAP icon registration.

The original failures remain preserved. The historical 503 cause is not established by the successful normal-bootstrap observation. The next narrow UI correction and same-record recapture will have separate source/build provenance. No award request, Grant or execution occurred.
