"""Explicit business review and accounting posting for synthetic test fixtures."""


def approve_and_post_bill(cipher, bill_id, *, approver, poster, approver_role="pm", requester_role="accountant",
                          poster_role="accountant", period_id=None, reason="", op_id=None):
    """Use the supplied people for two separate acts; return the posting command.

    The poster prepares the review request. This helper grants no identity or
    role and never routes business approval through generic execution.
    """
    approval = cipher.request_approval("bill.approve", bill_id, actor_role=requester_role, requested_by=poster)
    cipher.approve(approval["id"], approver=approver, approver_role=approver_role)
    return cipher.post_bill(bill_id, actor=poster, actor_role=poster_role,
                            period_id=period_id, reason=reason, op_id=op_id)
