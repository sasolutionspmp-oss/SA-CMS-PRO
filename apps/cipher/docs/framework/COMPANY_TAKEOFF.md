# Company drawing takeoff

Open **Company drawing takeoff** in the SAP UI5 navigation. `/company/takeoff?company=<Company ID>` lists authorized pre-award drawing sets; a selected set opens `/company/takeoff/<set ID>?company=<Company ID>`. A Company set has no synthetic Project or inferred pursuit owner.

1. Create a takeoff set with its title, discipline, drawing package and explicit basis.
2. Choose an authorized Company PDF source and stored revision. Inspect the exact drawing page. The viewer verifies downloaded bytes against the stored SHA and checks the actual PDF page count/frame. A drawing does not need embedded text or OCR to render.
3. On a current working revision, choose a canonical unit and enter an exact manual quantity within its precision, drawing locator and reason. No conversion, geometric scale or waste is inferred.
4. Save the working measurement. Read its immutable source/unit/quantity facts and the server’s separate current-use eligibility. Open its exact retained source when needed.

The register and saved measurement list request bounded pages with `limit=25`, `count_mode=none`, `total=null`; no exact total or eager full history is claimed. Known Company/User/Person/capability changes discard source-bearing read state. Denied/malformed metadata, revoked source bytes, wrong SHA/page count and stale sources cannot authorize the manual form. The backend independently rechecks current scope, source, unit and command authority.

Commands retain their original UUID and immutable inputs through uncertain replies while the view remains mounted. Global navigation protection prevents leaving an uncertain request in the SPA; recovery requires the original identity. This is not a persisted cross-reload command journal. Saved working quantities confer no acceptance, issue, award or accounting authority.

[Qualification and retained failure](evidence/r1/company-takeoff-r17/README.md) explain the real native correction. [Twelve actual screens](evidence/r1/company-takeoff-r17/ui/README.md) show desktop, tablet and phone flow. [Saved estimate-line evidence attachment](COMPANY_TAKEOFF_EVIDENCE.md) is now qualified in R18. [Measurement successors and revision comparison](COMPANY_TAKEOFF_SUCCESSORS.md) are now qualified in R19. Calibration authoring/independent verification and broader EST-02/UX-03 remain active.

[Reopen saved evidence and predecessor comparisons](COMPANY_TAKEOFF_HISTORY.md) after navigation or reload.
