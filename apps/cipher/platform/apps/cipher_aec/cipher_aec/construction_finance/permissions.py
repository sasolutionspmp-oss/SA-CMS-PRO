"""FIN snapshots are served only through explicit current-authority read models.

Native Frappe field selection cannot express citation and counterparty rights for
an immutable JSON snapshot. Generic list/get/export therefore fails closed;
scoped service reads check those dependencies individually on every boundary.
"""

def finance_query(user=None):
    return '1=0'


def finance_permission(doc, user=None, permission_type=None, ptype=None, **kwargs):
    return False
