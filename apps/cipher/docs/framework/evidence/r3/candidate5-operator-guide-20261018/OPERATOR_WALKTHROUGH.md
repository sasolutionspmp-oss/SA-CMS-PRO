# Candidate 5: Field and Quality/Safety

This guide describes published source at [`4b884afa`](https://github.com/sasolutionspmp-oss/SA-CMS-PRO/commit/4b884afa21ca1618bd47e2107d8212d261ecc1e9). It is not a record of running the program. Local trial results belong in a separate acceptance record.

## Field capture

Start online. Sign in, choose the correct Company and Project, and open **Offline field captures**. You need current Field access; cached information does not grant permission to save work on the server.

1. Under **Create a local profile**, choose a device registration UUID, label and separate local passphrase of at least 14 characters. Confirm the passphrase, opt in to browser storage, and choose an expiry from 1–168 hours. Use **Create encrypted profile**. Keep the registration UUID and passphrase: the screen does not restore the UUID after a reload.
2. Select **Register device online**, then **Refresh cached Project sources**. Registration identifies this capture profile; it is not proof of a particular physical device. Evidence refers to existing document revisions. New offline photo/file uploads are not included.
3. For a new daily report or T&M ticket, select **New offline capture**. To revise an existing record, first use **Read current base online** under **Prepare a current record for an offline revision**. Do that before disconnecting.
4. Enter the report/ticket, sources and quantities. Use **Seal encrypted capture** when ready. Sealing saves an encrypted local capture; it does not create the server Field record. An unfinished form is not a saved capture.
5. Reconnect with the same Company, Project and canonical person. Unlock the exact local profile if needed. Review the selected capture and check **I reviewed this exact sealed capture and its sources**.
6. Select **Stage selected capture**, then **Inspect original capture**. Staging stores the envelope for review; inspection checks its current disposition. Neither applies the Field command.
7. When inspection reports ready, select **Apply selected capture**. The server rechecks current access, sources and the base revision. Inspect the original receipt and confirm the resulting Field record. Reconnecting alone never applies captures.

If a base or source changed, preserve the sealed original and prepare an explicit linked replacement with a reason and current base. Do not edit the sealed capture or reuse its UUID for different content. If a result is uncertain, use **Recover original offline request** or inspect the original capture before another command. A locked navigation control is a recovery hold, not confirmation that the save failed. [Field screen and recovery flow][offline]

## Local storage and reload limits

| Situation | What to expect |
|---|---|
| Already-open page loses its connection | Sealed capture uses the encrypted browser profile; server actions still need a connection. Keep the authorized page available. |
| Reload, closed tab or offline cold start | Do not rely on reopening offline. The shell loads session/Project context from the server, the local key is held in memory, and the registration UUID input starts empty. Unsealed form recovery is not provided. |
| **Lock profile**, controlled logout or profile change | Decrypted views and the in-memory key clear. The default also removes that profile's encrypted copy; the explicit retention option keeps ciphertext subject to expiry. |
| Expiry or lost access | Expired profiles cannot unlock or sync. Access loss clears the view and requests local cleanup. Expiry is not a promise of background deletion while the browser is closed. |
| Storage error or full quota | Treat the capture as not saved unless the save completes. This is not a backup service. |
| Local discard or **Remove encrypted data from this browser** | Removes local data, including recovery journals when clearing all profiles. It does not cancel an uncertain server request or delete server records, original receipts or backups. |
| Server discard | A separate authorized, version-checked action redacts the offline envelope. It keeps the audit history and any original committed Field receipt. |

The supplied purge function needs no decryption, but this Candidate 5 page is reached through the signed-in shell. Do not depend on a signed-out purge screen. Browser deletion is not an attestation of secure device erasure. [Vault behavior][vault] · [Shell][shell] · [Server discard][offline-service]

## Quality and Safety

Open **Quality & Safety** in an authorized Project. Ordinary records cover inspections, deficiencies, safety observations and permit records. **Restricted incidents** is a separate, online-only area with separate access and evidence controls.

1. Select **New record**, or **New restricted incident** in that area. Enter the category, title, date, location, account of the work and required closure items. Attach permitted evidence. Restricted incidents also record the restricted account, people as recorded and immediate response.
2. Review and select **Save record**. Use **Submit for check** from **Next action**, add the required comment, review the revision/evidence, and select **Record action**.
3. An authorized person other than the author uses **Record independent check** with evidence, or **Return for revision**.
4. A third authorized person uses **Close documentary record**, with exact evidence for every required closure item. Alias accounts belonging to one person do not supply independent review.
5. Read **Record history** to distinguish revisions from decisions. Use **Create revision** for an eligible record or **Amend closed record** with a reason. Historical revisions remain readable and cannot receive new decisions.

A permit record records permit facts; it is not permission to perform hazardous work. Documentary close is not certification or regulatory submission. Quality/Safety does not use the Field offline capture queue. [Quality/Safety screen][quality] · [Editor][quality-editor]

Incident decision and closure evidence can only be selected from the current revision's retained evidence. A private-file upload confirmation alone does not mean the source is ready for incident use; current ingestion rights are separate. If the stale-record banner remains after the displayed Cancel/refresh instruction, record that as unresolved. See [source observations](OBSERVATIONS.md).

## Operational records and accounting

Field quantities, T&M acknowledgment, inspection checks and documentary closure are operational records. They do not create or change contracts, budgets, procurement, invoices, financial postings or payroll release. QuickBooks remains the initial official book of record. A saved Field or Quality/Safety receipt is not a QuickBooks accounting receipt or payment confirmation. [Field boundary][field] · [Accounting framework][accounting]

[offline]: https://github.com/sasolutionspmp-oss/SA-CMS-PRO/blob/4b884afa21ca1618bd47e2107d8212d261ecc1e9/apps/cipher/product/src/FieldOffline.tsx
[vault]: https://github.com/sasolutionspmp-oss/SA-CMS-PRO/blob/4b884afa21ca1618bd47e2107d8212d261ecc1e9/apps/cipher/product/src/field-offline-vault.ts#L80
[shell]: https://github.com/sasolutionspmp-oss/SA-CMS-PRO/blob/4b884afa21ca1618bd47e2107d8212d261ecc1e9/apps/cipher/product/src/App.tsx#L178
[offline-service]: https://github.com/sasolutionspmp-oss/SA-CMS-PRO/blob/4b884afa21ca1618bd47e2107d8212d261ecc1e9/apps/cipher/platform/apps/cipher_aec/cipher_aec/field_offline/service.py
[quality]: https://github.com/sasolutionspmp-oss/SA-CMS-PRO/blob/4b884afa21ca1618bd47e2107d8212d261ecc1e9/apps/cipher/product/src/QualitySafety.tsx
[quality-editor]: https://github.com/sasolutionspmp-oss/SA-CMS-PRO/blob/4b884afa21ca1618bd47e2107d8212d261ecc1e9/apps/cipher/product/src/QualitySafetyEditor.tsx
[field]: https://github.com/sasolutionspmp-oss/SA-CMS-PRO/blob/4b884afa21ca1618bd47e2107d8212d261ecc1e9/apps/cipher/product/src/FieldRecords.tsx#L59
[accounting]: https://github.com/sasolutionspmp-oss/SA-CMS-PRO/blob/4b884afa21ca1618bd47e2107d8212d261ecc1e9/apps/cipher/docs/framework/BACKEND_FRAMEWORK.md#L184
