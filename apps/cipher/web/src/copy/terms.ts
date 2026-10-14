export const practiceSentence = 'Practice data. Nothing here is real money and nothing is sent.';
export const statuses: Record<string, string> = {
  draft: 'Draft', pending: 'Waiting for review', granted: 'Approved', consumed: 'Completed',
  executed: 'Executed', closed: 'Closed', posted: 'Posted', approved: 'Approved, not posted',
  invalidated: 'Needs approval again', expired: 'Expired', rejected: 'Sent back',
  corrected: 'Corrected', void: 'Voided', paid: 'Paid', cancelled: 'Canceled',
};
export const statusText = (value: string) => statuses[value] ?? 'Recorded';
export const operations: Record<string, string> = {
  'bill.approve': 'Review pay app', 'commitment.execute': 'Review subcontract', 'change.execute': 'Review change order',
  'estimate.approve': 'Review estimate', 'prime_bill.approve': 'Review client pay app', 'payment.release': 'Review payment',
  'payment.release_retainage': 'Review retainage release', 'retainage.release': 'Review retainage',
  'bill.credit_note': 'Review supplier credit', 'bill.correct': 'Review bill correction',
};
export const approvalLabel = (operation: string) => operations[operation] ?? 'Review request';
export const help = {
  home: 'Start with requests waiting for review, then open a project to see its subcontracts and pay apps. These are synthetic records. This view reads information only; approval decisions and posting are unavailable.',
  projects: 'Open a project to see its budget, subcontracts, pay apps, and review requests. Search narrows the list as you type. Amounts come from the practice workspace; they are never sent to a bank.',
  record: 'This record opens read-only. Amounts and status reflect the practice workspace. Open a related record to follow the work. Approval decisions, edits, posting, and payments are unavailable in this view.',
  approvals: 'Read the subject, amount, and current status of each review request. A complete decision packet and authenticated human approval are still required before any decision. No request can be approved, posted, or paid here.',
};
